import os
import pickle
import io
from base64 import b64decode, b64encode
import json

from cachetools import cached

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError

from fsspec.spec import AbstractFileSystem, AbstractBufferedFile



not_secret = {"client_id": "464800473488-54uc38r5jos4pmk7vqfhg58jjjtd6vr9"
                           ".apps.googleusercontent.com",
              "client_secret": "919dmsddLQRbbXkt3-B7gFYd"}
client_config = {'installed': {
    'client_id': not_secret['client_id'],
    'client_secret': not_secret['client_secret'],
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://accounts.google.com/o/oauth2/token"
}}
tfile = os.path.join(os.path.expanduser("~"), '.google_drive_tokens')
scope_dict = {'full_control': 'https://www.googleapis.com/auth/drive',
              'read_only': 'https://www.googleapis.com/auth/drive.readonly'}

DIR_MIME_TYPE = 'application/vnd.google-apps.folder'


def _normalize_path(prefix, name):
    raw_prefix = prefix.strip('/')
    return '/' + '/'.join([raw_prefix, name])


def _finfo_from_response(f, path_prefix=None):
    ftype = 'directory' if f.get('mimeType') == DIR_MIME_TYPE else 'file'
    if path_prefix:
        name = _normalize_path(path_prefix, f['name'])
    else:
        name =f['name']
    info = {'id': f['id'],
            'name': name,
            'size': int(f.get('size', 0)),
            'type': ftype}
    return info


class GoogleDriveFileSystem(AbstractFileSystem):
    protocol = "gdrivefs"
    root_marker = '/'

    def __init__(self, root_file_id=None, token="browser",
                 access="full_control", spaces='drive', **kwargs):
        super().__init__(**kwargs)
        self.access = access
        self.scopes = [scope_dict[access]]
        self.token = token
        self.spaces = spaces
        self.root_file_id = root_file_id or 'root'
        self.connect(method=token)
        self.ls("")

    def connect(self, method=None):
        if method == 'browser':
            self._connect_browser()
        elif method == 'cache':
            self._connect_cache()
        else:
            raise ValueError(f"Invalid connection method `{method}`.")

    @staticmethod
    def load_tokens():
        """Get "browser" tokens from disc"""
        try:
            with open(tfile, 'rb') as f:
                tokens = pickle.load(f)
            # backwards compatability
            tokens = {k: (GoogleDriveFileSystem._dict_to_credentials(v)
                          if isinstance(v, dict) else v)
                      for k, v in tokens.items()}
        except Exception:
            tokens = {}
        GoogleDriveFileSystem.tokens = tokens

    @staticmethod
    def _save_tokens():
        with open(tfile, 'wb') as f:
            pickle.dump(GoogleDriveFileSystem.tokens, f, 2)

    def _connect_browser(self):
        flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
        credentials = flow.run_console()
        self.tokens[self.access] = credentials
        self._save_tokens()
        self.service = build('drive', 'v3', credentials=credentials).files()

    def _connect_cache(self):
        credentials = self.tokens[self.access]
        self.service = build('drive', 'v3', credentials=credentials).files()

    def info(self, path, trashed=False, **kwargs):
        file_id = self.path_to_file_id(path, trashed=trashed)
        return self._info_by_id(file_id)

    def _info_by_id(self, file_id, path_prefix=None):
        fields = 'id, name, size, mimeType'
        response = self.service.get(fileId=file_id, fields=fields,
                                    ).execute()
        return _finfo_from_response(response, path_prefix)

    def ls(self, path, detail=False, trashed=False):
        if path is None or path == '/' or path == "":
            file_id = self.root_file_id
        else:
            file_id = self.path_to_file_id(path, trashed=trashed)
        files = self._list_directory_by_id(file_id, trashed=trashed,
                                           path_prefix=path)
        if detail:
            return files
        else:
            return sorted([f["name"] for f in files])

    @cached(cache={})
    def _list_directory_by_id(self, file_id, trashed=False, path_prefix=None):
        all_files = []
        page_token = None
        fields = 'nextPageToken, files(id, name, size, mimeType)'
        query = f"'{file_id}' in parents  "
        if not trashed:
            query += "and trashed = false "
        while True:
            response = self.service.list(q=query,
                                         spaces=self.spaces, fields=fields,
                                         pageToken=page_token).execute()
            for f in response.get('files', []):
                all_files.append(_finfo_from_response(f, path_prefix))
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        return all_files

    @cached(cache={})
    def path_to_file_id(self, path, parent=None, trashed=False):
        items = path.strip('/').split('/')
        if parent is None:
            parent = self.root_file_id
        top_file_id = self._get_directory_child_by_name(items[0], parent,
                                                        trashed=trashed)
        if len(items) == 1:
            return top_file_id
        else:
            sub_path = '/'.join(items[1:])
            return self.path_to_file_id(sub_path, parent=top_file_id,
                                        trashed=trashed)

    def _get_directory_child_by_name(self, child_name, directory_file_id,
                                     trashed=False):
        all_children = self._list_directory_by_id(directory_file_id,
                                                  trashed=trashed)
        possible_children = []
        for child in all_children:
            if child['name'] == child_name:
                possible_children.append(child['id'])
        if len(possible_children) == 0:
            raise KeyError(f'Directory {directory_file_id} has no child '
                           f'named {child_name}')
        if len(possible_children) == 1:
            return possible_children[0]
        else:
            raise KeyError(f'Directory {directory_file_id} has more than one '
                           f'child named {child_name}. Unable to resolve path '
                           'to file_id.')

    def _open(self, path, mode="rb", **kwargs):
        return GoogleDriveFile(self, path, mode=mode, **kwargs)


GoogleDriveFileSystem.load_tokens()

DEFAULT_BLOCK_SIZE = 5 * 2 ** 20


class GoogleDriveFile(AbstractBufferedFile):

    def __init__(self, fs, path, mode='rb', block_size=DEFAULT_BLOCK_SIZE,
                 consistency='md5', autocommit=True, **kwargs):
        """
        Open a file.

        Parameters
        ----------
        fs: instance of GoogleDriveFileSystem
        mode: str
            Normal file modes. Currently only 'wb' amd 'rb'.
        block_size: int
            Buffer size for reading or writing
        """
        super().__init__(fs, path, mode, block_size, autocommit=autocommit,
                         **kwargs)

        if mode == 'wb':
            self.location = None
        else:
            self.file_id = fs.path_to_file_id(path)

    def _fetch_range(self, start=None, end=None):
        """ Get data from Google Drive

        start, end : None or integers
            if not both None, fetch only given range
        """

        if start is not None or end is not None:
            start = start or 0
            end = end or 0
            head = {'Range': 'bytes=%i-%i' % (start, end - 1)}
        else:
            head = {}
        try:
            files_service = self.fs.service
            media_obj = files_service.get_media(fileId=self.file_id)
            media_obj.headers.update(head)
            data = media_obj.execute()
            return data
        except HttpError as e:
            # TODO : doc says server might send everything if range is outside
            if 'not satisfiable' in str(e):
                return b''
            raise

    def _upload_chunk(self, final=False):
        """ Write one part of a multi-block file upload

        Parameters
        ----------
        final: bool
            Complete and commit upload
        """
        self.buffer.seek(0)
        data = self.buffer.getvalue()
        head = {}
        l = len(data)
        if final and self.autocommit:
            if l:
                part = "%i-%i" % (self.offset, self.offset + l - 1)
                head['Content-Range'] = 'bytes %s/%i' % (part, self.offset + l)
            else:
                # closing when buffer is empty
                head['Content-Range'] = 'bytes */%i' % self.offset
                data = None
        else:
            head['Content-Range'] = 'bytes %i-%i/*' % (
                self.offset, self.offset + l - 1)
        head.update({'Content-Type': 'application/octet-stream',
                     'Content-Length': str(l)})
        req = self.fs.service._http.request
        head, body = req(self.location, method="PUT", body=data,
                         headers=head)
        status = int(head['status'])
        assert status < 400, "Init upload failed"
        if status in [200, 201]:
            # server thinks we are finished, this should happen
            # only when closing
            self.file_id = json.loads(body.decode())['id']
        elif 'Range' in head:
            assert status == 308
            assert head['Range'].split("=") == part
        else:
            raise IOError
        return True

    def commit(self):
        """If not auto-committing, finalize file"""
        self.autocommit = True
        self._upload_chunk(final=True)

    def _initiate_upload(self):
        """ Create multi-upload """
        parent_id = self.fs.path_to_file_id(self.fs._parent(self.path))
        head = {"Content-Type": "application/json; charset=UTF-8"}
        # also allows description, MIME type, version, thumbnail...
        body = json.dumps({"name": self.path.rsplit('/', 1)[-1],
                           "parents": [parent_id]}).encode()
        req = self.fs.service._http.request
        r = req("https://www.googleapis.com/upload/drive/v3/files"
                "?uploadType=resumable", method='POST',
                headers=head, body=body)
        head = r[0]
        assert int(head['status']) < 400, "Init upload failed"
        self.location = r[0]['location']
