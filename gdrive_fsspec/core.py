from functools import cached_property
import re
import json
import os

from fsspec.spec import AbstractFileSystem, AbstractBufferedFile
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.credentials import AnonymousCredentials
from google.oauth2 import service_account
import pydata_google_auth


scope_dict = {
    "full_control": "https://www.googleapis.com/auth/drive",
    "read_only": "https://www.googleapis.com/auth/drive.readonly",
}

DIR_MIME_TYPE = "application/vnd.google-apps.folder"
fields = ",".join(
    [
        "name",
        "id",
        "size",
        "description",
        "trashed",
        "mimeType",
        "version",
        "createdTime",
        "modifiedTime",
        "capabilities",
    ]
)


def _normalize_path(prefix, name):
    raw_prefix = prefix.strip("/")
    return "/" + "/".join([raw_prefix, name])


def _finfo_from_response(f, path_prefix=None):
    # strictly speaking, other types might be capable of having children,
    # such as packages
    ftype = "directory" if f.get("mimeType") == DIR_MIME_TYPE else "file"
    if path_prefix:
        name = _normalize_path(path_prefix, f["name"])
    else:
        name = f["name"]
    f.pop("capabilities", None)  # remove annoying big dict
    info = {"name": name.lstrip("/"), "size": int(f.get("size", 0)), "type": ftype}
    f.update(info)
    return f


class GoogleDriveFileSystem(AbstractFileSystem):
    protocol = "gdrive"
    root_marker = ""

    def __init__(
        self,
        root_file_id=None,
        token="cache",
        access="full_control",
        spaces="drive",
        creds=None,
        **kwargs,
    ):
        """
        Access to doogle-grive as a file-system

        :param root_file_id: str or None
            If you have a share, drive or folder ID to treat as the FS root, enter
            it here. Otherwise, you will get your default drive
        :param token: str
            One of "anon", "browser", "cache", "service_account". Using "browser" will prompt a URL to
            be put in a browser, and cache the response for future use with token="cache".
            "browser" will remove any previously cached token file if it exists.
        :param access: str
            One of "full_control", "read_only"
        :param spaces:
            Category of files to search; can be 'drive', 'appDataFolder' and 'photos'.
            Of these, only the first is general
        :param creds: None or dict
            Required just for "service_account" token, a dict containing the service account
            credentials obtainend in GCP console. The dict content is the same as the json file
            downloaded from GCP console. More details can be found here:
            https://cloud.google.com/iam/docs/service-account-creds#key-types
            This credential can be usful when integrating with other GCP services, and when you
            don't want the user to be prompted to authenticate.
            The files need to be shared with the service account email address, that can be found
            in the json file.
        :param kwargs:
            Passed to parent
        """
        super().__init__(**kwargs)
        self.access = access
        self.scopes = [scope_dict[access]]
        self.spaces = spaces
        self.root_file_id = root_file_id or "root"
        self.creds = creds
        self.connect(method=token)

    def connect(self, method=None):
        if method == "browser":
            cred = self._connect_browser()
        elif method == "cache":
            cred = self._connect_cache()
        elif method == "anon":
            cred = AnonymousCredentials()
        elif method == "service_account":
            cred = self._connect_service_account()
        else:
            raise ValueError(f"Invalid connection method `{method}`.")
        srv = build("drive", "v3", credentials=cred)
        self.srv = srv
        self.files = srv.files()

    @property
    def _user_credentials_cache_path(self):
        return pydata_google_auth.cache.READ_WRITE._path

    def _connect_browser(self):
        try:
            os.remove(self._user_credentials_cache_path)
        except OSError:
            pass
        return self._connect_cache()

    def _connect_cache(self):
        return pydata_google_auth.get_user_credentials(
            self.scopes, use_local_webserver=True
        )

    def _connect_service_account(self):
        return service_account.Credentials.from_service_account_info(
            info=self.creds, scopes=self.scopes
        )

    @cached_property
    def drives(self):
        """Drives accessible to the current user"""
        out = []
        page_token = None
        while True:
            ret = self.srv.drives().list(pageToken=page_token).execute()
            out.extend(ret["drives"])
            page_token = ret.get("nextPageToken")
            if page_token is None:
                break
        return out

    def mkdir(self, path, create_parents=True, **kwargs):
        if create_parents and self._parent(path):
            self.makedirs(self._parent(path), exist_ok=True)
        parent_id = self.path_to_file_id(self._parent(path))
        meta = {
            "name": path.rstrip("/").rsplit("/", 1)[-1],
            "mimeType": DIR_MIME_TYPE,
            "parents": [parent_id],
        }
        self.files.create(body=meta).execute()
        self.invalidate_cache(self._parent(path))

    def makedirs(self, path, exist_ok=True):
        if self.isdir(path):
            if exist_ok:
                return
            else:
                raise FileExistsError(path)
        if self._parent(path):
            self.makedirs(self._parent(path), exist_ok=True)
        self.mkdir(path, create_parents=False)

    def _delete(self, file_id):
        self.files.delete(fileId=file_id).execute()

    def rm(self, path, recursive=True, maxdepth=None):
        if recursive is False and self.isdir(path) and self.ls(path):
            raise ValueError("Attempt to delete non-empty folder")
        self._delete(self.path_to_file_id(path))
        self.invalidate_cache(path)
        self.invalidate_cache(self._parent(path))

    def rmdir(self, path):
        if not self.isdir(path):
            raise ValueError("Path is not a directory")
        self.rm(path, recursive=False)

    def _info_by_id(self, file_id, path_prefix=None):
        response = self.files.get(
            fileId=file_id,
            fields=fields,
        ).execute()
        return _finfo_from_response(response, path_prefix)

    def export(self, path, mime_type):
        """Convert a google-native file to another format and download

        mime_type is something like "text/plain"
        """
        file_id = self.path_to_file_id(path)
        return self.files.export(fileId=file_id, mimeType=mime_type).execute()

    def split_drive(self, path):
        root, *_ = path.rsplit("/", 1)
        if ":" in root:
            drive, rest = path.split(":", 1)
        else:
            return None, path
        if len(drive) == 19 and drive[0] == "0":
            # + other conditions, seems to be "^0[a-zA-Z0-9_-]{18}$"
            return drive, rest
        drive = [_["id"] for _ in self.drives if _["name"] == drive]
        if len(drive) == 0:
            raise ValueError(f"Drive name {drive} not found")
        elif len(drive) == 1:
            return drive[0], rest
        else:
            raise ValueError(f"Drive name {drive} refers to multiple shared drives")

    def ls(self, path, detail=False, trashed=False):
        path = self._strip_protocol(path)
        if path in [None, "/"]:
            path0 = ""
        else:
            path0 = path
        files = self._ls_from_cache(path0)
        drive, path = self.split_drive(path0)

        if not files:
            if path == "":
                file_id = self.root_file_id
            else:
                file_id = self.path_to_file_id(path, trashed=trashed, drive=drive)
            files = self._list_directory_by_id(
                file_id, trashed=trashed, path_prefix=path, drive=drive
            )
            if files:
                self.dircache[path0] = files
            else:
                file_id = self.path_to_file_id(path0, trashed=trashed, drive=drive)
                files = [self._info_by_id(file_id)]

        if detail:
            return files
        else:
            return sorted([f["name"] for f in files])

    @staticmethod
    def _drive_kw(drive=None):
        if drive is not None:
            return dict(
                includeItemsFromAllDrives=True,
                corpora="drive",
                supportsAllDrives=True,
                driveId=drive,
            )
        else:
            return {}

    def _list_directory_by_id(
        self, file_id, trashed=False, path_prefix=None, drive=None
    ):
        all_files = []
        page_token = None
        afields = "nextPageToken, files(%s)" % fields
        if file_id == "root" and drive is not None:
            query = f"'{drive}' in parents "
        else:
            query = f"'{file_id}' in parents "
        if not trashed:
            query += "and trashed = false "
        kwargs = self._drive_kw(drive)
        while True:
            response = self.files.list(
                q=query,
                spaces=self.spaces,
                fields=afields,
                pageToken=page_token,
                **kwargs,
            ).execute()
            for f in response.get("files", []):
                all_files.append(_finfo_from_response(f, path_prefix))
            page_token = response.get("nextPageToken", None)
            if page_token is None:
                break
        return all_files

    def path_to_file_id(self, path, parent=None, trashed=False, drive=None):
        items = path.strip("/").split("/")
        if path in ["", "/", "root", self.root_file_id]:
            return self.root_file_id
        if parent is None:
            parent = self.root_file_id
        top_file_id = self._get_directory_child_by_name(
            items[0], parent, trashed=trashed, drive=drive
        )
        if len(items) == 1:
            return top_file_id
        else:
            sub_path = "/".join(items[1:])
            return self.path_to_file_id(
                sub_path, parent=top_file_id, trashed=trashed, drive=drive
            )

    def _get_directory_child_by_name(
        self, child_name, directory_file_id, trashed=False, drive=None
    ):
        all_children = self._list_directory_by_id(
            directory_file_id, trashed=trashed, drive=drive
        )
        possible_children = []
        for child in all_children:
            if child["name"] == child_name:
                possible_children.append(child["id"])
        if len(possible_children) == 0:
            raise FileNotFoundError(
                f"Directory {directory_file_id} has no child named {child_name}"
            )
        if len(possible_children) == 1:
            return possible_children[0]
        else:
            raise KeyError(
                f"Directory {directory_file_id} has more than one "
                f"child named {child_name}. Unable to resolve path "
                "to file_id."
            )

    def _open(self, path, mode="rb", **kwargs):
        return GoogleDriveFile(self, path, mode=mode, **kwargs)


DEFAULT_BLOCK_SIZE = 5 * 2**20


class GoogleDriveFile(AbstractBufferedFile):
    def __init__(
        self,
        fs,
        path,
        mode="rb",
        block_size=DEFAULT_BLOCK_SIZE,
        autocommit=True,
        **kwargs,
    ):
        """
        Open a file.

        Parameters
        ----------
        fs: instance of GoogleDriveFileSystem
        mode: str
            Normal file modes. Currently only 'wb' amd 'rb'.
        block_size: int
            Buffer size for reading or writing (default 5MB)
        """
        super().__init__(fs, path, mode, block_size, autocommit=autocommit, **kwargs)

        if mode == "wb":
            self.location = None
        else:
            self.file_id = fs.info(path)["id"]
            self._media_object = None

    def _fetch_range(self, start=None, end=None):
        """Get data from Google Drive

        start, end : None or integers
            if not both None, fetch only given range
        """

        if self._media_object is None:
            self._media_object = self.fs.files.get_media(fileId=self.file_id)
        if start is not None or end is not None:
            start = start or 0
            end = end or 0
            self._media_object.headers["Range"] = "bytes=%i-%i" % (start, end - 1)
        else:
            self._media_object.headers.pop("Range", None)
        try:
            data = self._media_object.execute()
            return data
        except HttpError as e:
            # TODO : doc says server might send everything if range is outside
            if "not satisfiable" in str(e):
                return b""
            raise

    def _upload_chunk(self, final=False):
        """Write one part of a multi-block file upload

        Parameters
        ----------
        final: bool
            Complete and commit upload
        """
        self.buffer.seek(0)
        data = self.buffer.getvalue()
        head = {}
        length = len(data)
        if final and self.autocommit:
            if length:
                part = "%i-%i" % (self.offset, self.offset + length - 1)
                head["Content-Range"] = "bytes %s/%i" % (part, self.offset + length)
            else:
                # closing when buffer is empty
                head["Content-Range"] = "bytes */%i" % self.offset
                data = None
        else:
            head["Content-Range"] = "bytes %i-%i/*" % (
                self.offset,
                self.offset + length - 1,
            )
        head.update(
            {"Content-Type": "application/octet-stream", "Content-Length": str(length)}
        )
        req = self.fs.files._http.request
        head, body = req(self.location, method="PUT", body=data, headers=head)
        status = int(head["status"])
        assert status < 400, "Init upload failed"
        if status in [200, 201]:
            # server thinks we are finished - this should happen
            # only when closing
            self.file_id = json.loads(body.decode())["id"]
        elif "range" in head:
            assert status == 308
        else:
            raise IOError
        return True

    def commit(self):
        """If not auto-committing, finalize file"""
        self.autocommit = True
        self._upload_chunk(final=True)

    def _initiate_upload(self):
        """Create multi-upload"""
        parent_id = self.fs.path_to_file_id(self.fs._parent(self.path))
        head = {"Content-Type": "application/json; charset=UTF-8"}
        # also allows description, MIME type, version, thumbnail...
        body = json.dumps(
            {"name": self.path.rsplit("/", 1)[-1], "parents": [parent_id]}
        ).encode()
        req = self.fs.files._http.request  # partial with correct creds
        # TODO : this creates a new file. If the file exists, you should
        #   update it by getting the ID and using PATCH, else you get two
        #   identically-named files
        r = req(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
            method="POST",
            headers=head,
            body=body,
        )
        head = r[0]
        assert int(head["status"]) < 400, "Init upload failed"
        self.location = r[0]["location"]

    def discard(self):
        """Cancel in-progress multi-upload"""
        if self.location is None:
            return
        uid = re.findall("upload_id=([^&=?]+)", self.location)
        head, _ = self.gcsfs._call(
            "DELETE",
            "https://www.googleapis.com/upload/drive/v3/files",
            params={"uploadType": "resumable", "upload_id": uid},
        )
        assert int(head["status"]) < 400, "Cancel upload failed"
