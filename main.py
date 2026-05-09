import os
import io
import hashlib
import time
import signal
import json
import logging
import fnmatch
import threading
import queue
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError

# --- CONSTANTS ---
LARGE_FILE_THRESHOLD_BYTES = 100 * 1024 * 1024   # 100 MB: dùng resumable chunk lớn
LARGE_FILE_CHUNK_SIZE      = 100 * 1024 * 1024   # 100 MB per chunk (tối ưu cho file .sql lớn)
SMALL_FILE_CHUNK_SIZE      =   1 * 1024 * 1024   # 1  MB per chunk (tiến độ mượt hơn)
MD5_READ_CHUNK             =  64 * 1024           # 64 KB — cân bằng giữa tốc độ và bộ nhớ

# Retry khi gặp lỗi mạng: backoff tăng dần (giây)
RETRY_DELAYS = [10, 30, 60, 120, 300]             # tối đa 5 lần thử lại
RETRYABLE_NETWORK_ERRORS = (
    BrokenPipeError,
    ConnectionError,
    ConnectionResetError,
    ConnectionAbortedError,
    TimeoutError,
)

CONFIG_FILE = "config.json"
IGNORE_FILE = ".syncignore"
SESSION_DIR = ".upload_sessions"
LOG_FILE = "history.log"
SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = "credentials.json"

# Nguồn sự thật duy nhất cho tất cả các key config và giá trị mặc định.
# Thêm key mới vào đây là đủ — load_config() sẽ tự lo phần còn lại.
CONFIG_DEFAULTS = {
    "DRIVE_FOLDER_ID":       "1Gxd4eejYA3o7Rwwd_W62rP8xBamhGpvW",
    "WATCH_FOLDERS":         ["data-upload"],
    "IGNORE_STARTUP_FILES":  True,
    "MAX_UPLOAD_SPEED_MBPS": 0,
    "TELEGRAM_BOT_TOKEN":    "",
    "TELEGRAM_CHAT_ID":      "",
    "NOTIFY_SIZE_LIMIT_MB":  5,
    "DELETE_REMOTE_FILES":   False,
    "SYNC_REMOTE_TO_LOCAL":  False,
    "ENABLE_PARALLEL":       True,
    "MAX_WORKERS":           3,
}


# --- 4. HỆ THỐNG CONFIG ---
def load_config():
    # -- Tạo file mới nếu chưa tồn tại --
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump(CONFIG_DEFAULTS, f, indent=4)
        return dict(CONFIG_DEFAULTS)   # trả về bản sao để tránh mutate

    # -- Đọc file hiện có --
    with open(CONFIG_FILE, "r") as f:
        cfg = json.load(f)

    updated = False

    # Điền các key còn thiếu từ CONFIG_DEFAULTS
    for key, default_val in CONFIG_DEFAULTS.items():
        if key not in cfg:
            cfg[key] = default_val
            updated = True

    # Ghi lại nếu có thay đổi
    if updated:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=4)

    return cfg


CONFIG = load_config()


# --- 1. HỆ THỐNG LOG ---
def setup_logger():
    logger = logging.getLogger("UploadBot")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
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
        clean_msg = msg.encode("ascii", "ignore").decode("ascii").strip()
        if clean_msg:
            logger.info(clean_msg)   # ghi clean_msg, không phải msg gốc


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
        with open(IGNORE_FILE, "w", encoding="utf-8") as f:
            f.write(
                "# Bỏ qua các file ẩn\n.*\n# Bỏ qua các thư mục cụ thể\n__pycache__/\nnode_modules/\n# Bỏ qua các file tạm\n*.tmp\n*.log\n"
            )
    with open(IGNORE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def is_ignored(file_path, base_folder, patterns):
    try:
        rel_path = os.path.relpath(file_path, base_folder).replace("\\", "/")
        name = os.path.basename(file_path)
        for pattern in patterns:
            if pattern.endswith("/"):
                if f"{pattern[:-1]}" in rel_path.split("/") or rel_path.startswith(
                    pattern
                ):
                    return True
            elif fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern):
                return True
        return False
    except ValueError:
        return False

def _wait_for_stable_size(file_path: str, stable_secs: int = 5, poll_interval: int = 2) -> bool:
    """
    Chờ cho đến khi kích thước file không đổi trong ít nhất stable_secs giây.

    Mục đích: tránh upload file đang được ghi dở (race condition với backup server).

    Returns:
        True  — file ổn định, sẵn sàng upload
        False — file biến mất trong khi đợi
    """
    last_size = -1
    stable_elapsed = 0
    file_name = os.path.basename(file_path)
    while stable_elapsed < stable_secs:
        try:
            current_size = os.path.getsize(file_path)
        except OSError:
            return False
        if current_size == last_size:
            stable_elapsed += poll_interval
        else:
            if last_size != -1:   # size đang thay đổi — chỉ log khi file đột ngột lớn hơn
                log_print(f"⏳ File đang được ghi, đợi ổn định: {file_name} ({current_size/(1024**3):.2f} GB)")
            stable_elapsed = 0
            last_size = current_size
        if stable_elapsed < stable_secs:
            time.sleep(poll_interval)
    return True


# --- CẤU TRÚC CHÍNH ---
class GoogleDriveManager:
    def __init__(self, parent_folder_id):
        self.parent_id = parent_folder_id
        self.service = self._get_service()
        self.md5_cache = {}
        self.ignored_files_at_startup = {}
        if not os.path.exists(SESSION_DIR):
            os.makedirs(SESSION_DIR)

    def scan_startup_files(self, root_folder_path):
        if not CONFIG.get("IGNORE_STARTUP_FILES", True):
            return
        log_print(
            f"🔍 Đang quét và đánh dấu bỏ qua các file cũ trong: {root_folder_path}..."
        )
        ignore_patterns = load_ignore_patterns()
        for dirpath, dirnames, filenames in os.walk(root_folder_path):
            dirnames[:] = [
                d
                for d in dirnames
                if not is_ignored(
                    os.path.join(dirpath, d), root_folder_path, ignore_patterns
                )
            ]
            for filename in filenames:
                file_path = os.path.abspath(os.path.join(dirpath, filename))
                if not is_ignored(file_path, root_folder_path, ignore_patterns):
                    try:
                        self.ignored_files_at_startup[file_path] = os.path.getmtime(
                            file_path
                        )
                    except OSError:
                        pass

    def _get_service(self):
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        return build("drive", "v3", credentials=creds)

    @staticmethod
    def _build_service():
        """Tạo service Google Drive độc lập — dùng cho worker threads (thread-safe)."""
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build("drive", "v3", credentials=creds)

    def _create_drive_folder(self, folder_name, parent_id):
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        log_print(f"📁 Đang tạo thư mục trên Drive: {folder_name}...")
        folder = (
            self.service.files()
            .create(body=file_metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        return folder.get("id")

    def _get_items_in_folder(self, folder_id):
        query = f"'{folder_id}' in parents and trashed=false"
        items = []
        page_token = None
        while True:
            results = (
                self.service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, md5Checksum, mimeType)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            items.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break
        files = {
            f["name"]: {"id": f["id"], "md5": f.get("md5Checksum")}
            for f in items
            if f["mimeType"] != "application/vnd.google-apps.folder"
        }
        folders = {
            f["name"]: f["id"]
            for f in items
            if f["mimeType"] == "application/vnd.google-apps.folder"
        }
        return files, folders

    def _calculate_md5(self, file_path):
        try:
            mtime = os.path.getmtime(file_path)
            if (
                file_path in self.md5_cache
                and self.md5_cache[file_path]["mtime"] == mtime
            ):
                return self.md5_cache[file_path]["md5"]
            hash_md5 = hashlib.md5()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(MD5_READ_CHUNK), b""):
                    hash_md5.update(chunk)
            computed_md5 = hash_md5.hexdigest()
            self.md5_cache[file_path] = {"mtime": mtime, "md5": computed_md5}
            return computed_md5
        except PermissionError:
            log_print(
                f"⚠️ Bỏ qua: '{os.path.basename(file_path)}' (File đang được copy/tải xuống)"
            )
            return None
        except FileNotFoundError:
            return None

    # --- 3. TRUE RESUME UPLOAD ---
    def upload_file(self, file_path, existing_file_id=None, parent_id=None, service=None):
        """Upload một file lên Drive. Truyền `service` riêng khi gọi từ worker thread."""
        parent_id = parent_id or self.parent_id
        svc = service or self.service          # dùng service truyền vào nếu có
        thread_tag = f"[{threading.current_thread().name}] "
        try:
            file_name = os.path.basename(file_path)

            # Kiểm tra file ổn định (chưa bị ghi dở) trước khi upload
            if not _wait_for_stable_size(file_path):
                log_print(f"{thread_tag}⚠️ File biến mất khi đợi: {file_name} — bỏ qua.")
                return None

            file_size_bytes = os.path.getsize(file_path)
            file_size_mb = file_size_bytes / (1024 * 1024)

            # Tối ưu chunk size theo kích thước file
            if file_size_bytes >= LARGE_FILE_THRESHOLD_BYTES:
                chunk_size = LARGE_FILE_CHUNK_SIZE
                log_print(f"{thread_tag}📦 File lớn ({file_size_mb:.0f} MB) — dùng chunk 100 MB: {file_name}")
            else:
                chunk_size = SMALL_FILE_CHUNK_SIZE

            file_md5 = self._calculate_md5(file_path)
            session_file = (
                os.path.join(SESSION_DIR, f"{file_md5}.json") if file_md5 else None
            )

            for attempt in range(len(RETRY_DELAYS) + 1):
                try:
                    media = MediaFileUpload(file_path, chunksize=chunk_size, resumable=True)
                    saved_uri = None

                    if session_file and os.path.exists(session_file):
                        with open(session_file, "r") as f:
                            saved_uri = json.load(f).get("uri")

                    if existing_file_id:
                        if not saved_uri:
                            log_print(f"{thread_tag}🔄 Đang cập nhật thay đổi: {file_name}...")
                        request = svc.files().update(
                            fileId=existing_file_id, media_body=media, fields="id"
                        )
                    else:
                        if not saved_uri:
                            log_print(f"{thread_tag}⬆️ Đang tải lên file mới: {file_name}...")
                        request = svc.files().create(
                            body={"name": file_name, "parents": [parent_id]},
                            media_body=media,
                            fields="id",
                            supportsAllDrives=True,
                        )

                    if saved_uri:
                        log_print(f"{thread_tag}⚡ Khôi phục phiên tải lên dang dở của: {file_name}...")
                        request.resumable_uri = saved_uri
                        request.resumable_progress = 0

                    response = None
                    start_time = time.time()
                    first_chunk = True
                    max_speed_mb = float(CONFIG.get("MAX_UPLOAD_SPEED_MBPS", 0))

                    last_progress_mb = 0
                    while response is None:
                        chunk_start = time.time()
                        status, response = request.next_chunk()

                        if first_chunk and session_file and request.resumable_uri:
                            with open(session_file, "w") as f:
                                json.dump({"uri": request.resumable_uri}, f)
                            first_chunk = False

                        if status:
                            last_progress_mb = status.resumable_progress / (1024 * 1024)
                            chunk_elapsed = time.time() - chunk_start
                            if max_speed_mb > 0:
                                expected_time = (chunk_size / (1024 * 1024)) / max_speed_mb
                                if chunk_elapsed < expected_time:
                                    time.sleep(expected_time - chunk_elapsed)

                            progress = int(status.progress() * 100)
                            elapsed_time = time.time() - start_time
                            if elapsed_time > 0:
                                speed_mb = (
                                    status.resumable_progress / (1024 * 1024)
                                ) / elapsed_time
                                log_print(
                                    f"\r   ⏳ Tiến độ: {progress}% hoàn thành | Tốc độ: {speed_mb:.1f} MB/s   ",
                                    is_progress=True,
                                )
                            else:
                                log_print(
                                    f"\r   ⏳ Tiến độ: {progress}% hoàn thành...",
                                    is_progress=True,
                                )
                    
                    # Upload thành công, thoát khỏi vòng retry
                    break

                except RETRYABLE_NETWORK_ERRORS as e:
                    if attempt < len(RETRY_DELAYS):
                        delay = RETRY_DELAYS[attempt]
                        prog_info = f" [Đã up: {last_progress_mb:.1f}/{file_size_mb:.1f} MB]" if 'last_progress_mb' in locals() and last_progress_mb > 0 else ""
                        log_print(f"\n⚠️ {thread_tag}Lỗi mạng ({e.__class__.__name__}): {file_name}{prog_info}. Thử lại sau {delay}s (lần {attempt+1}/{len(RETRY_DELAYS)})...")
                        time.sleep(delay)
                    else:
                        if session_file and os.path.exists(session_file):
                            os.remove(session_file)
                        raise e
                except HttpError as e:
                    if e.resp.status in [500, 502, 503, 504] and attempt < len(RETRY_DELAYS):
                        delay = RETRY_DELAYS[attempt]
                        prog_info = f" [Đã up: {last_progress_mb:.1f}/{file_size_mb:.1f} MB]" if 'last_progress_mb' in locals() and last_progress_mb > 0 else ""
                        log_print(f"\n⚠️ {thread_tag}Lỗi server Google ({e.resp.status}): {file_name}{prog_info}. Thử lại sau {delay}s (lần {attempt+1}/{len(RETRY_DELAYS)})...")
                        time.sleep(delay)
                    elif e.resp.status in [404, 401, 403, 400]:
                        if session_file and os.path.exists(session_file):
                            os.remove(session_file)
                        log_print(
                            f"\n⚠️ {thread_tag}Phiên tải lên cũ đã hết hạn. Đang tải lại từ đầu..."
                        )
                        # Truyền lại service để không mất thread-safety
                        return self.upload_file(file_path, existing_file_id, parent_id, service)
                    else:
                        if attempt == len(RETRY_DELAYS) and session_file and os.path.exists(session_file):
                            os.remove(session_file)
                        raise e

            # Luôn hiển thị 100% khi kết thúc để người dùng yên tâm
            log_print(
                f"\r   ⏳ Tiến độ: 100% hoàn thành | Tốc độ: Hoàn tất!        ",
                is_progress=True,
            )

            log_print(
                f"\n✅ Thành công! ID: {response.get('id')}                                  \n"
            )
            if session_file and os.path.exists(session_file):
                os.remove(session_file)

            notify_limit_mb = float(CONFIG.get("NOTIFY_SIZE_LIMIT_MB", 1024))
            if file_size_mb >= notify_limit_mb:
                send_telegram_notify(
                    f"🚀 Sếp ơi, file '{file_name}' ({file_size_mb:.1f} MB) đã được up xong an toàn!"
                )

            return response.get("id")

        except Exception as e:
            log_print(f"\n❌ Thất bại {file_name}: {e}\n")
            return None

    def delete_file(self, file_name, file_id):
        try:
            log_print(f"🗑️ Đang xóa file trên Drive (cho vào thùng rác): {file_name}...")
            self.service.files().update(
                fileId=file_id, body={"trashed": True}
            ).execute()
            log_print(f"✅ Đã đưa '{file_name}' vào thùng rác.\n")
        except Exception as e:
            log_print(f"❌ Lỗi khi xóa {file_name}: {e}\n")

    def download_file(self, file_id, file_path):
        try:
            log_print(f"📥 Đang tải xuống: {os.path.basename(file_path)}...")
            request = self.service.files().get_media(fileId=file_id)
            with io.FileIO(file_path, "wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        log_print(
                            f"\r   ⏳ Tiến độ tải xuống: {progress}% hoàn thành...",
                            is_progress=True,
                        )
            log_print(
                f"\r✅ Tải xuống thành công: {os.path.basename(file_path)}                  \n"
            )
            return True
        except Exception as e:
            log_print(f"\n❌ Tải xuống thất bại: {e}\n")
            return False

    def upload_directory(self, root_folder_path, upload_fn=None):
        """
        Quét cây thư mục và đồng bộ lên Drive.

        Args:
            upload_fn: Hàm gọi khi cần upload một file.
                       Signature: upload_fn(file_path, existing_file_id=None, parent_id=None)
                       Mặc định: self.upload_file  (chế độ tuần tự)
                       Truyền queue_manager.enqueue  (chế độ song song)
        """
        _upload = upload_fn or self.upload_file
        if not os.path.exists(root_folder_path):
            log_print(f"❌ Thư mục '{root_folder_path}' không tồn tại!")
            return False

        log_print(f"\n🔍 Bắt đầu đồng bộ cây thư mục từ: {root_folder_path}")
        folder_id_map = {os.path.abspath(root_folder_path): self.parent_id}
        ignore_patterns = load_ignore_patterns()

        has_skipped_files = False
        for dirpath, dirnames, filenames in os.walk(root_folder_path):
            dirnames[:] = [
                d
                for d in dirnames
                if not is_ignored(
                    os.path.join(dirpath, d), root_folder_path, ignore_patterns
                )
            ]

            current_local_dir = os.path.abspath(dirpath)
            current_drive_parent_id = folder_id_map.get(current_local_dir)
            if not current_drive_parent_id:
                continue

            drive_files, drive_folders = self._get_items_in_folder(
                current_drive_parent_id
            )

            for dirname in dirnames:
                local_sub_dir = os.path.join(current_local_dir, dirname)
                if dirname in drive_folders:
                    folder_id_map[local_sub_dir] = drive_folders[dirname]
                else:
                    new_folder_id = self._create_drive_folder(
                        dirname, current_drive_parent_id
                    )
                    folder_id_map[local_sub_dir] = new_folder_id

            for drive_foldername, drive_folder_id in drive_folders.items():
                if drive_foldername not in dirnames:
                    if CONFIG.get("SYNC_REMOTE_TO_LOCAL", False):
                        local_sub_dir = os.path.join(
                            current_local_dir, drive_foldername
                        )
                        if not os.path.exists(local_sub_dir):
                            os.makedirs(local_sub_dir)
                        dirnames.append(drive_foldername)
                        folder_id_map[local_sub_dir] = drive_folder_id
                    elif CONFIG.get("DELETE_REMOTE_FILES", True):
                        self.delete_file(drive_foldername, drive_folder_id)

            for filename in filenames:
                file_path = os.path.join(current_local_dir, filename)
                if is_ignored(file_path, root_folder_path, ignore_patterns):
                    continue

                abs_path = os.path.abspath(file_path)
                if (
                    CONFIG.get("IGNORE_STARTUP_FILES", True)
                    and abs_path in self.ignored_files_at_startup
                ):
                    try:
                        if (
                            os.path.getmtime(abs_path)
                            <= self.ignored_files_at_startup[abs_path]
                        ):
                            continue
                    except OSError:
                        pass

                local_md5 = self._calculate_md5(file_path)
                if not local_md5:
                    has_skipped_files = True
                    continue

                drive_file = drive_files.get(filename)
                if not drive_file:
                    _upload(file_path, parent_id=current_drive_parent_id)
                else:
                    if local_md5 != drive_file["md5"]:
                        _upload(
                            file_path,
                            existing_file_id=drive_file["id"],
                            parent_id=current_drive_parent_id,
                        )

            local_files_in_dir = set(
                f
                for f in filenames
                if not is_ignored(
                    os.path.join(current_local_dir, f),
                    root_folder_path,
                    ignore_patterns,
                )
            )
            for drive_filename, drive_file_info in drive_files.items():
                if drive_filename not in local_files_in_dir:
                    if CONFIG.get("SYNC_REMOTE_TO_LOCAL", False):
                        local_file_path = os.path.join(
                            current_local_dir, drive_filename
                        )
                        if not is_ignored(
                            local_file_path, root_folder_path, ignore_patterns
                        ):
                            self.download_file(drive_file_info["id"], local_file_path)
                    elif CONFIG.get("DELETE_REMOTE_FILES", True):
                        self.delete_file(drive_filename, drive_file_info["id"])

        log_print("\n🎉 Hoàn tất quá trình đồng bộ toàn bộ cây thư mục!")
        return has_skipped_files


# ---------------------------------------------------------------------------
# UPLOAD QUEUE MANAGER — hàng đợi + ThreadPoolExecutor
# ---------------------------------------------------------------------------


class UploadQueueManager:
    """
    Quản lý upload song song qua Queue + ThreadPoolExecutor.

    Luồng dữ liệu:
        enqueue(file_path) → queue.Queue
            ↓ (dispatcher thread)
        ThreadPoolExecutor.submit(_worker)
            ↓ (worker thread — có service riêng, thread-safe)
        drive_manager.upload_file(service=<riêng>)
            ↓
        send_telegram_notify()
    """

    def __init__(self, drive_manager: "GoogleDriveManager", max_workers: int = 5):
        self.drive        = drive_manager
        self._queue       = queue.Queue()
        self._in_progress = set()          # tránh enqueue trùng file
        self._lock        = threading.Lock()
        self._executor    = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="Uploader",
        )
        self._stopped = False
        # Dispatcher chạy ngầm, lấy item từ queue rồi submit vào executor
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher, name="UploadDispatcher", daemon=True
        )
        self._dispatcher_thread.start()
        log_print(f"🚀 UploadQueueManager khởi động — {max_workers} workers song song.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, file_path: str, existing_file_id: str = None, parent_id: str = None):
        """Đẩy một file vào hàng đợi. Bỏ qua nếu file đang được xử lý."""
        abs_path = os.path.abspath(file_path)
        with self._lock:
            if abs_path in self._in_progress:
                log_print(f"⏭️  Bỏ qua (đang upload): {os.path.basename(abs_path)}")
                return
            self._in_progress.add(abs_path)
        self._queue.put((abs_path, existing_file_id, parent_id))
        log_print(f"📥 Đã thêm vào hàng đợi: {os.path.basename(abs_path)} "
                  f"(queue size: {self._queue.qsize()})")

    def shutdown(self, wait: bool = True):
        """Dừng dispatcher và chờ tất cả worker hoàn thành."""
        self._stopped = True
        self._queue.put(None)          # sentinel để thoát dispatcher
        self._executor.shutdown(wait=wait)
        log_print("🛑 UploadQueueManager đã dừng.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _dispatcher(self):
        """Thread ngầm: lấy item từ queue và submit vào ThreadPoolExecutor."""
        while not self._stopped:
            item = self._queue.get()
            if item is None:           # sentinel — thoát
                break
            file_path, existing_file_id, parent_id = item
            self._executor.submit(self._worker, file_path, existing_file_id, parent_id)

    def _worker(self, file_path: str, existing_file_id: str, parent_id: str):
        """
        Worker chạy trong thread riêng:
        - Tạo service Google Drive độc lập (thread-safe)
        - Upload file
        - Gửi Telegram notify nếu thành công
        - Bắt mọi exception — KHÔNG để lỗi 1 file ảnh hưởng file khác
        """
        file_name = os.path.basename(file_path)
        try:
            # Mỗi worker tạo service riêng → thread-safe hoàn toàn
            svc = GoogleDriveManager._build_service()
            self.drive.upload_file(
                file_path,
                existing_file_id=existing_file_id,
                parent_id=parent_id,
                service=svc,
            )
        except Exception as e:
            log_print(f"\n❌ [Worker] Lỗi upload '{file_name}': {e}\n")
        finally:
            # Luôn xóa khỏi in_progress dù thành công hay thất bại
            with self._lock:
                self._in_progress.discard(os.path.abspath(file_path))


class WatcherHandler(FileSystemEventHandler):
    def __init__(self, drive_manager, folder_path, queue_manager=None):
        self.drive = drive_manager
        self.folder_path = folder_path
        self.queue_manager = queue_manager          # None → chế độ tuần tự
        self.ignore_patterns = load_ignore_patterns()
        self.timer = None
        self.lock = threading.Lock()                # bảo vệ timer
        self.sync_lock = threading.Lock()           # chỉ dùng ở chế độ tuần tự
        self.sync_pending = False

    def on_modified(self, event):
        if event.is_directory:
            return
        if is_ignored(event.src_path, self.folder_path, self.ignore_patterns):
            return

        with self.lock:
            # Chế độ tuần tự: nếu đang sync thì chỉ đánh dấu pending
            if self.queue_manager is None and self.sync_lock.locked():
                self.sync_pending = True
                return
            if self.timer:
                self.timer.cancel()
            # Debounce 2 giây sau sự kiện cuối cùng mới bắt đầu
            self.timer = threading.Timer(2.0, self.execute_sync, [event.src_path])
            self.timer.start()

    def on_created(self, event):
        self.on_modified(event)

    def on_deleted(self, event):
        self.on_modified(event)

    def on_moved(self, event):
        self.on_modified(event)

    def execute_sync(self, src_path):
        log_print(f"\n👀 Phát hiện thay đổi tại: {os.path.basename(src_path)}")

        if self.queue_manager is not None:
            # ----------------------------------------------------------------
            # CHẾ ĐỘ SONG SONG: scan + enqueue, không block Watchdog thread
            # ----------------------------------------------------------------
            log_print("⚡ Chế độ song song: đang quét và đưa vào hàng đợi...")
            self.drive.upload_directory(
                self.folder_path,
                upload_fn=self.queue_manager.enqueue,
            )
            log_print(
                f"\n👀 Tiếp tục theo dõi thư mục '{self.folder_path}'... (Bấm Ctrl+C để thoát)"
            )
        else:
            # ----------------------------------------------------------------
            # CHẾ ĐỘ TUẦN TỰ: giữ nguyên logic cũ
            # ----------------------------------------------------------------
            with self.sync_lock:
                self.sync_pending = False
                log_print("⏳ Bắt đầu đồng bộ hàng loạt...")
                has_skipped = self.drive.upload_directory(self.folder_path)

                if has_skipped or self.sync_pending:
                    reason = (
                        "Một số file đang bận (đang copy)"
                        if has_skipped
                        else "Có thay đổi mới trong lúc đồng bộ"
                    )
                    log_print(f"⚠️ {reason}. Sẽ tự động quét lại sau 5 giây...")
                    with self.lock:
                        if self.timer:
                            self.timer.cancel()
                        self.timer = threading.Timer(5.0, self.execute_sync, [src_path])
                        self.timer.start()
                else:
                    log_print(
                        f"\n👀 Tiếp tục theo dõi thư mục '{self.folder_path}'... (Bấm Ctrl+C để thoát)"
                    )


def start_watching(drive_manager, folder_paths, queue_manager=None):
    observer = Observer()
    for folder_path in folder_paths:
        event_handler = WatcherHandler(drive_manager, folder_path, queue_manager=queue_manager)
        observer.schedule(event_handler, folder_path, recursive=True)
        log_print(f"\n👀 Đang theo dõi thư mục '{folder_path}'...")

    mode = "⚡ Song song" if queue_manager else "📼 Tuần tự"
    log_print(f"\n🚀 Tool đang chạy ngầm [{mode}]... (Bấm Ctrl+C để thoát)")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        if queue_manager:
            log_print("\n⏳ Đang chờ các upload đang dở hoàn thành...")
            queue_manager.shutdown(wait=True)

def signal_handler(sig, frame):
    """Ctrl+C: raise KeyboardInterrupt thông thường để finally trong start_watching chạy."""
    log_print("\n\n🛑 Đang dừng bot, đợi upload dở hoàn tất... (bấm Ctrl+C lần 2 để thoát ngậy)")
    # Không dùng os._exit() — phải để finally trong start_watching gọi queue_manager.shutdown()
    signal.signal(sig, signal.SIG_DFL)  # lần 2 bấm Ctrl+C sẽ thoát ngậy
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    # Kiểm tra credentials.json trước khi làm bất cứ điều gì
    if not os.path.exists(CREDENTIALS_FILE):
        log_print(f"❌ Không tìm thấy file '{CREDENTIALS_FILE}'.")
        log_print(
            "   Vui lòng tải credentials.json từ Google Cloud Console và đặt vào thư mục gốc."
        )
        os._exit(1)

    FOLDER_ID = CONFIG.get("DRIVE_FOLDER_ID")
    folders_to_watch = CONFIG.get("WATCH_FOLDERS", [])

    if not folders_to_watch:
        log_print("❌ Không có thư mục nào để theo dõi trong WATCH_FOLDERS!")
        os._exit(1)

    if not FOLDER_ID:
        log_print("❌ Chưa cấu hình DRIVE_FOLDER_ID trong config.json!")
        os._exit(1)

    drive = GoogleDriveManager(FOLDER_ID)

    # Khởi tạo UploadQueueManager nếu được bật
    queue_manager = None
    if CONFIG.get("ENABLE_PARALLEL", True):
        max_workers = int(CONFIG.get("MAX_WORKERS", 5))
        queue_manager = UploadQueueManager(drive, max_workers=max_workers)

    for folder_to_watch in folders_to_watch:
        if not os.path.exists(folder_to_watch):
            os.makedirs(folder_to_watch)

        if CONFIG.get("IGNORE_STARTUP_FILES", True):
            drive.scan_startup_files(folder_to_watch)
        else:
            drive.upload_directory(folder_to_watch)

    start_watching(drive, folders_to_watch, queue_manager=queue_manager)
