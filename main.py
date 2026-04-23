import os
import io
import hashlib
import time
import sys
import signal
import json
import logging
import fnmatch
import urllib.request
import urllib.parse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

CONFIG_FILE = 'config.json'
IGNORE_FILE = '.syncignore'
SESSION_DIR = '.upload_sessions'
LOG_FILE = 'history.log'
SCOPES = ['https://www.googleapis.com/auth/drive']
CREDENTIALS_FILE = 'credentials.json'

# --- 4. HỆ THỐNG CONFIG ---
def load_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "DRIVE_FOLDER_ID": "1Gxd4eejYA3o7Rwwd_W62rP8xBamhGpvW",
            "WATCH_FOLDER": "data-upload",
            "MAX_UPLOAD_SPEED_MBPS": 0,
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "NOTIFY_SIZE_LIMIT_MB": 5,
            "DELETE_REMOTE_FILES": False,
            "SYNC_REMOTE_TO_LOCAL": False
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        return default_config
    with open(CONFIG_FILE, 'r') as f:
        # Tự động cập nhật thêm key mới nếu config cũ chưa có
        cfg = json.load(f)
        defaults = {
            "MAX_UPLOAD_SPEED_MBPS": 0,
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "NOTIFY_SIZE_LIMIT_MB": 5,
            "DELETE_REMOTE_FILES": False,
            "SYNC_REMOTE_TO_LOCAL": False
        }
        updated = False
        for k, v in defaults.items():
            if k not in cfg:
                cfg[k] = v
                updated = True
        if updated:
            with open(CONFIG_FILE, 'w') as f2:
                json.dump(cfg, f2, indent=4)
        return cfg

CONFIG = load_config()

# --- 1. HỆ THỐNG LOG ---
def setup_logger():
    logger = logging.getLogger("UploadBot")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
    logger.addHandler(fh)
    return logger

logger = setup_logger()

def log_print(msg, is_progress=False):
    """In ra màn hình và ghi vào file log. Nếu là progress bar thì không ghi log để tránh rác file"""
    if is_progress:
        print(msg, end="", flush=True)
    else:
        print(msg)
        # Bỏ các emoji khi ghi vào log cho sạch
        clean_msg = msg.encode('ascii', 'ignore').decode('ascii').strip()
        if clean_msg:
            logger.info(msg)

# --- TELEGRAM BOT ---
def send_telegram_notify(msg):
    token = CONFIG.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = CONFIG.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log_print(f"⚠️ Không thể gửi thông báo Telegram: {e}")

# --- 2. HỆ THỐNG IGNORE ---
def load_ignore_patterns():
    if not os.path.exists(IGNORE_FILE):
        with open(IGNORE_FILE, 'w', encoding='utf-8') as f:
            f.write("# Bỏ qua các file ẩn\n.*\n# Bỏ qua các thư mục cụ thể\n__pycache__/\nnode_modules/\n# Bỏ qua các file tạm\n*.tmp\n*.log\n")
    with open(IGNORE_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

def is_ignored(file_path, base_folder, patterns):
    try:
        rel_path = os.path.relpath(file_path, base_folder).replace('\\', '/')
        name = os.path.basename(file_path)
        for pattern in patterns:
            if pattern.endswith('/'):
                if f"{pattern[:-1]}" in rel_path.split('/') or rel_path.startswith(pattern):
                    return True
            elif fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return True
        return False
    except ValueError:
        return False

# --- CẤU TRÚC CHÍNH ---
class GoogleDriveManager:
    def __init__(self, parent_folder_id):
        self.parent_id = parent_folder_id
        self.service = self._get_service()
        self.md5_cache = {}
        if not os.path.exists(SESSION_DIR):
            os.makedirs(SESSION_DIR)

    def _get_service(self):
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        return build('drive', 'v3', credentials=creds)

    def _create_drive_folder(self, folder_name, parent_id):
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
        log_print(f"📁 Đang tạo thư mục trên Drive: {folder_name}...")
        folder = self.service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
        return folder.get('id')

    def _get_items_in_folder(self, folder_id):
        query = f"'{folder_id}' in parents and trashed=false"
        items = []
        page_token = None
        while True:
            results = self.service.files().list(
                q=query, fields="nextPageToken, files(id, name, md5Checksum, mimeType)",
                pageSize=1000, pageToken=page_token
            ).execute()
            items.extend(results.get('files', []))
            page_token = results.get('nextPageToken')
            if not page_token: break
        files = {f['name']: {'id': f['id'], 'md5': f.get('md5Checksum')} for f in items if f['mimeType'] != 'application/vnd.google-apps.folder'}
        folders = {f['name']: f['id'] for f in items if f['mimeType'] == 'application/vnd.google-apps.folder'}
        return files, folders

    def _calculate_md5(self, file_path):
        try:
            mtime = os.path.getmtime(file_path)
            if file_path in self.md5_cache and self.md5_cache[file_path]['mtime'] == mtime:
                return self.md5_cache[file_path]['md5']
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            computed_md5 = hash_md5.hexdigest()
            self.md5_cache[file_path] = {'mtime': mtime, 'md5': computed_md5}
            return computed_md5
        except PermissionError:
            log_print(f"⚠️ Bỏ qua: '{os.path.basename(file_path)}' (File đang được copy/tải xuống)")
            return None
        except FileNotFoundError:
            return None

    # --- 3. TRUE RESUME UPLOAD ---
    def upload_file(self, file_path, existing_file_id=None, parent_id=None):
        parent_id = parent_id or self.parent_id
        try:
            file_name = os.path.basename(file_path)
            file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
            chunk_size = 1 * 1024 * 1024 # Giảm xuống 1MB để thấy tiến độ mượt hơn
            media = MediaFileUpload(file_path, chunksize=chunk_size, resumable=True)
            
            file_md5 = self._calculate_md5(file_path)
            session_file = os.path.join(SESSION_DIR, f"{file_md5}.json") if file_md5 else None
            saved_uri = None
            
            if session_file and os.path.exists(session_file):
                with open(session_file, 'r') as f:
                    saved_uri = json.load(f).get('uri')
            
            if existing_file_id:
                if not saved_uri: log_print(f"🔄 Đang cập nhật thay đổi: {file_name}...")
                request = self.service.files().update(fileId=existing_file_id, media_body=media, fields='id')
            else:
                if not saved_uri: log_print(f"⬆️ Đang tải lên file mới: {file_name}...")
                request = self.service.files().create(body={'name': file_name, 'parents': [parent_id]}, media_body=media, fields='id', supportsAllDrives=True)
            
            if saved_uri:
                log_print(f"⚡ Khôi phục phiên tải lên dang dở của: {file_name}...")
                request.resumable_uri = saved_uri
                request.resumable_progress = 0
            
            response = None
            start_time = time.time()
            first_chunk = True
            max_speed_mb = float(CONFIG.get("MAX_UPLOAD_SPEED_MBPS", 0))
            
            while response is None:
                try:
                    chunk_start = time.time()
                    status, response = request.next_chunk()
                    
                    if first_chunk and session_file and request.resumable_uri:
                        with open(session_file, 'w') as f:
                            json.dump({'uri': request.resumable_uri}, f)
                        first_chunk = False

                    if status:
                        chunk_elapsed = time.time() - chunk_start
                        if max_speed_mb > 0:
                            expected_time = (chunk_size / (1024 * 1024)) / max_speed_mb
                            if chunk_elapsed < expected_time:
                                time.sleep(expected_time - chunk_elapsed)

                        progress = int(status.progress() * 100)
                        elapsed_time = time.time() - start_time
                        if elapsed_time > 0:
                            speed_mb = (status.resumable_progress / (1024 * 1024)) / elapsed_time
                            log_print(f"\r   ⏳ Tiến độ: {progress}% hoàn thành | Tốc độ: {speed_mb:.1f} MB/s   ", is_progress=True)
                        else:
                            log_print(f"\r   ⏳ Tiến độ: {progress}% hoàn thành...", is_progress=True)
                except HttpError as e:
                    if e.resp.status in [404, 401, 403, 400]:
                        if session_file and os.path.exists(session_file): os.remove(session_file)
                        log_print(f"\n⚠️ Phiên tải lên cũ đã hết hạn. Đang tải lại từ đầu...")
                        return self.upload_file(file_path, existing_file_id, parent_id)
                    else:
                        raise e
            
            # Luôn hiển thị 100% khi kết thúc để người dùng yên tâm
            log_print(f"\r   ⏳ Tiến độ: 100% hoàn thành | Tốc độ: Hoàn tất!        ", is_progress=True)

            log_print(f"\n✅ Thành công! ID: {response.get('id')}                                  \n")
            if session_file and os.path.exists(session_file):
                os.remove(session_file)
                
            notify_limit_mb = float(CONFIG.get("NOTIFY_SIZE_LIMIT_MB", 1024))
            if file_size_mb >= notify_limit_mb:
                send_telegram_notify(f"🚀 Sếp ơi, file '{file_name}' ({file_size_mb:.1f} MB) đã được up xong an toàn!")
                
            return response.get('id')
            
        except Exception as e:
            log_print(f"\n❌ Thất bại {file_name}: {e}\n")
            return None

    def delete_file(self, file_name, file_id):
        try:
            log_print(f"🗑️ Đang xóa file trên Drive (cho vào thùng rác): {file_name}...")
            self.service.files().update(fileId=file_id, body={'trashed': True}).execute()
            log_print(f"✅ Đã đưa '{file_name}' vào thùng rác.\n")
        except Exception as e:
            log_print(f"❌ Lỗi khi xóa {file_name}: {e}\n")

    def download_file(self, file_id, file_path):
        try:
            log_print(f"📥 Đang tải xuống: {os.path.basename(file_path)}...")
            request = self.service.files().get_media(fileId=file_id)
            with io.FileIO(file_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=1024*1024)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        log_print(f"\r   ⏳ Tiến độ tải xuống: {progress}% hoàn thành...", is_progress=True)
            log_print(f"\r✅ Tải xuống thành công: {os.path.basename(file_path)}                  \n")
            return True
        except Exception as e:
            log_print(f"\n❌ Tải xuống thất bại: {e}\n")
            return False

    def upload_directory(self, root_folder_path):
        if not os.path.exists(root_folder_path):
            log_print(f"❌ Thư mục '{root_folder_path}' không tồn tại!")
            return
            
        log_print(f"\n🔍 Bắt đầu đồng bộ cây thư mục từ: {root_folder_path}")
        folder_id_map = {os.path.abspath(root_folder_path): self.parent_id}
        ignore_patterns = load_ignore_patterns()
        
        for dirpath, dirnames, filenames in os.walk(root_folder_path):
            dirnames[:] = [d for d in dirnames if not is_ignored(os.path.join(dirpath, d), root_folder_path, ignore_patterns)]
            
            current_local_dir = os.path.abspath(dirpath)
            current_drive_parent_id = folder_id_map.get(current_local_dir)
            if not current_drive_parent_id: continue
                
            drive_files, drive_folders = self._get_items_in_folder(current_drive_parent_id)
            
            for dirname in dirnames:
                local_sub_dir = os.path.join(current_local_dir, dirname)
                if dirname in drive_folders:
                    folder_id_map[local_sub_dir] = drive_folders[dirname]
                else:
                    new_folder_id = self._create_drive_folder(dirname, current_drive_parent_id)
                    folder_id_map[local_sub_dir] = new_folder_id
                    
            for drive_foldername, drive_folder_id in drive_folders.items():
                if drive_foldername not in dirnames:
                    if CONFIG.get("SYNC_REMOTE_TO_LOCAL", False):
                        local_sub_dir = os.path.join(current_local_dir, drive_foldername)
                        if not os.path.exists(local_sub_dir):
                            os.makedirs(local_sub_dir)
                        dirnames.append(drive_foldername)
                        folder_id_map[local_sub_dir] = drive_folder_id
                    elif CONFIG.get("DELETE_REMOTE_FILES", True):
                        self.delete_file(drive_foldername, drive_folder_id)
                    
            has_skipped_files = False
            for filename in filenames:
                file_path = os.path.join(current_local_dir, filename)
                if is_ignored(file_path, root_folder_path, ignore_patterns):
                    continue
                    
                local_md5 = self._calculate_md5(file_path)
                if not local_md5:
                    has_skipped_files = True
                    continue
                    
                drive_file = drive_files.get(filename)
                if not drive_file:
                    self.upload_file(file_path, parent_id=current_drive_parent_id)
                else:
                    if local_md5 != drive_file['md5']:
                        self.upload_file(file_path, existing_file_id=drive_file['id'], parent_id=current_drive_parent_id)
                        
            local_files_in_dir = set(f for f in filenames if not is_ignored(os.path.join(current_local_dir, f), root_folder_path, ignore_patterns))
            for drive_filename, drive_file_info in drive_files.items():
                if drive_filename not in local_files_in_dir:
                    if CONFIG.get("SYNC_REMOTE_TO_LOCAL", False):
                        local_file_path = os.path.join(current_local_dir, drive_filename)
                        if not is_ignored(local_file_path, root_folder_path, ignore_patterns):
                            self.download_file(drive_file_info['id'], local_file_path)
                    elif CONFIG.get("DELETE_REMOTE_FILES", True):
                        self.delete_file(drive_filename, drive_file_info['id'])
                    
        log_print("\n🎉 Hoàn tất quá trình đồng bộ toàn bộ cây thư mục!")
        return has_skipped_files


import threading

class WatcherHandler(FileSystemEventHandler):
    def __init__(self, drive_manager, folder_path):
        self.drive = drive_manager
        self.folder_path = folder_path
        self.ignore_patterns = load_ignore_patterns()
        self.timer = None
        self.lock = threading.Lock()

    def on_modified(self, event):
        if is_ignored(event.src_path, self.folder_path, self.ignore_patterns):
            return
        
        with self.lock:
            if self.timer:
                self.timer.cancel()
            
            # Đợi 2 giây sau sự kiện cuối cùng mới bắt đầu đồng bộ
            self.timer = threading.Timer(2.0, self.execute_sync, [event.src_path])
            self.timer.start()

    def on_created(self, event): self.on_modified(event)
    def on_deleted(self, event): self.on_modified(event)
    def on_moved(self, event): self.on_modified(event)

    def execute_sync(self, src_path):
        log_print(f"\n👀 Phát hiện thay đổi tại: {os.path.basename(src_path)}")
        log_print("⏳ Bắt đầu đồng bộ hàng loạt...")
        
        # Nếu có file bị skip (do đang copy), upload_directory trả về True
        has_skipped = self.drive.upload_directory(self.folder_path)
        
        if has_skipped:
            log_print("⚠️ Một số file đang bận (đang copy). Sẽ tự động quét lại sau 5 giây...")
            with self.lock:
                if self.timer: self.timer.cancel()
                self.timer = threading.Timer(5.0, self.execute_sync, [src_path])
                self.timer.start()
        else:
            log_print(f"\n👀 Tiếp tục theo dõi thư mục '{self.folder_path}'... (Bấm Ctrl+C để thoát)")


def start_watching(drive_manager, folder_path):
    event_handler = WatcherHandler(drive_manager, folder_path)
    observer = Observer()
    observer.schedule(event_handler, folder_path, recursive=True)
    observer.start()
    log_print(f"\n👀 Tool đang chạy ngầm và theo dõi thư mục '{folder_path}'... (Bấm Ctrl+C để thoát)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    observer.join()

def signal_handler(sig, frame):
    log_print("\n\n🛑 Đang dừng mọi tiến trình và tắt Tool an toàn... Hẹn gặp lại!")
    os._exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    
    FOLDER_ID = CONFIG.get("DRIVE_FOLDER_ID")
    folder_to_watch = CONFIG.get("WATCH_FOLDER")

    if not os.path.exists(folder_to_watch):
        os.makedirs(folder_to_watch)

    drive = GoogleDriveManager(FOLDER_ID)
    drive.upload_directory(folder_to_watch)
    start_watching(drive, folder_to_watch)