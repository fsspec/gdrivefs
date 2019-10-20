import io
import requests
import os
import warnings
import pickle

from cachetools import cached

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import fsspec
from fsspec import AbstractFileSystem



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

class GoogleDriveFileSystem(AbstractFileSystem):
    protocol = "gdrive"

    def __init__(self, token="browser", access="full_control", **kwargs):
        super().__init__(**kwargs)
        self.access = access
        self.scopes = [scope_dict[access]]
        self.token = token
        self.connect(method=token)
        #self.ls("")

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
        #except Exception as e:
        #    warnings.warn('Saving token cache failed: ' + str(e))

    def _connect_browser(self):
        flow = InstalledAppFlow.from_client_config(client_config, self.scopes)
        credentials = flow.run_console()
        self.tokens[self.access] = credentials
        self._save_tokens()
        self.service = build('drive', 'v3', credentials=credentials)

    def _connect_cache(self):
        access = self.access
        if access in self.tokens:
            credentials = self.tokens[access]
            self.service = build('drive', 'v3', credentials=credentials)

    @cached(cache={})
    def _list_directory_by_id(self, file_id):
        all_files = []
        page_token = None
        spaces = 'drive'
        fields = 'nextPageToken, files(id, name, size, mimeType)'
        while True:
            response = self.service.files().list(q=f"'{file_id}' in parents ",
                                            spaces=spaces, fields=fields,
                                            pageToken=page_token).execute()
            all_files += response.get('files', [])
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        return all_files

    def ls(self, path, detail=False):
        if path is None or path == '/' or path == "":
            file_id = 'root'
        else:
            file_id = self.path_to_file_id(path)
        files = self._list_directory_by_id(file_id)
        if detail:
            return files
        else:
            return sorted([f["name"] for f in files])


    def _get_directory_child_by_name(self, child_name, directory_file_id):
        all_children = self._list_directory_by_id(directory_file_id)
        for child in all_children:
            if child['name'] == child_name:
                return child['id']
        raise KeyError(f'directory {directory_file_id} has no child named {child_name}')

    @cached(cache={})
    def path_to_file_id(self, path, parent=None):
        items = path.strip('/').split('/')
        top_file_id = self._get_directory_child_by_name(items[0], parent)
        if len(items) == 1:
            return top_file_id
        else:
            sub_path = '/'.join(items[1:])
            return self.path_to_file_id(sub_path, parent=top_file_id)

    def _open_file_id(self, file_id, **kwargs):
         request = self.service.files().get_media(fileId=file_id)
         return request.execute()

    def _open(self, path, mode="rb", **kwargs):
        if mode != "rb":
            raise NotImplementedError
        file_id = self.path_to_file_id(path)
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print("Download %d%%." % int(status.progress() * 100))
        return fh

GoogleDriveFileSystem.load_tokens()

DEFAULT_BLOCK_SIZE = 100 * 1024 * 1024

class GoogleDriveFile(fsspec.spec.AbstractBufferedFile):

    def __init__(self, gdfs, file_id, mode='rb', block_size=DEFAULT_BLOCK_SIZE,
                 acl=None, consistency='md5', metadata=None,
                 autocommit=True, **kwargs):
        """
        Open a file.

        Parameters
        ----------
        gdfs: instance of GoogleDriveFileSystem
        file_id: str
            Google drive unique file_id
        mode: str
            Normal file modes. Currently only 'wb' amd 'rb'.
        block_size: int
            Buffer size for reading or writing
        """
        super().__init__(gdfs, path, mode, block_size, autocommit=autocommit,
                         **kwargs)
        self.gdfs = gcsfs
        self.fike_id = file_id
        self.metadata = metadata
        if mode == 'wb':
            if self.blocksize < GCS_MIN_BLOCK_SIZE:
                warnings.warn('Setting block size to minimum value, 2**18')
                self.blocksize = GCS_MIN_BLOCK_SIZE

    def _fetch_range(self, start=None, end=None):
        """ Get data from GCS

        start, end : None or integers
            if not both None, fetch only given range
        """
        if start is not None or end is not None:
            start = start or 0
            end = end or 0
            head = {'Range': 'bytes=%i-%i' % (start, end - 1)}
        else:
            head = None
        try:
            r = self.gcsfs._call('GET', self.details['mediaLink'],
                                 headers=head)
            data = r.content
            return data
        except RuntimeError as e:
            if 'not satisfiable' in str(e):
                return b''
            raise

    #
    # @_tracemethod
    # def ls(self, path, detail=False):
    #     """List files under the given path."""
    #
    #     if path in ['/', '']:
    #         if detail:
    #             return self._list_buckets()
    #         else:
    #             return self.buckets
    #     elif path.endswith("/"):
    #         return self._ls(path, detail)
    #     else:
    #         combined_listing = self._ls(path, detail) + self._ls(path + "/",
    #                                                              detail)
    #         if detail:
    #             combined_entries = dict(
    #                 (l["name"], l) for l in combined_listing)
    #             combined_entries.pop(path + "/", None)
    #             return list(combined_entries.values())
    #         else:
    #             return list(set(combined_listing) - {path + "/"})
    #
    # def _ls(self, path, detail=False):
    #     listing = self._list_objects(path)
    #     bucket, key = split_path(path)
    #
    #     item_details = listing["items"]
    #
    #     pseudodirs = [{
    #             'bucket': bucket,
    #             'name': bucket + "/" + prefix,
    #             'kind': 'storage#object',
    #             'size': 0,
    #             'storageClass': 'DIRECTORY',
    #             'type': 'directory'
    #         }
    #         for prefix in listing["prefixes"]
    #     ]
    #     out = item_details + pseudodirs
    #     if detail:
    #         return out
    #     else:
    #         return sorted([o['name'] for o in out])
    #
    # @_tracemethod
    # def _list_objects(self, path):
    #     path = norm_path(path)
    #
    #     clisting = self._maybe_get_cached_listing(path)
    #     if clisting:
    #         return clisting
    #
    #     listing = self._do_list_objects(path)
    #     retrieved_time = time.time()
    #
    #     self._listing_cache[path] = (retrieved_time, listing)
    #     return listing
    #
    # @_tracemethod
    # def _do_list_objects(self, path, max_results=None):
    #     """Object listing for the given {bucket}/{prefix}/ path."""
    #     bucket, prefix = split_path(path)
    #     if not prefix:
    #         prefix = None
    #
    #     prefixes = []
    #     items = []
    #     page = self._call('GET', 'b/{}/o/', bucket,
    #                       delimiter="/", prefix=prefix, maxResults=max_results
    #                       ).json()
    #
    #     assert page["kind"] == "storage#objects"
    #     prefixes.extend(page.get("prefixes", []))
    #     items.extend([i for i in page.get("items", [])
    #                   if prefix is None
    #                   or i['name'].rstrip('/') == prefix.rstrip('/')
    #                   or i['name'].startswith(prefix.rstrip('/') + '/')])
    #     next_page_token = page.get('nextPageToken', None)
    #
    #     while next_page_token is not None:
    #         page = self._call('GET', 'b/{}/o/', bucket,
    #                           delimiter="/", prefix=prefix,
    #                           maxResults=max_results, pageToken=next_page_token
    #                           ).json()
    #
    #         assert page["kind"] == "storage#objects"
    #         prefixes.extend(page.get("prefixes", []))
    #         items.extend([
    #             i for i in page.get("items", [])
    #         ])
    #         next_page_token = page.get('nextPageToken', None)
    #
    #     prefixes = [p for p in prefixes
    #                 if prefix is None or prefix.rstrip('/') + '/' in p]
    #     result = {
    #         "kind": "storage#objects",
    #         "prefixes": prefixes,
    #         "items": [self._process_object(bucket, i) for i in items],
    #     }
    #     return result
    #
    # def ls(file_id, parentpath, detail=False, **kwargs):
    #     if path == "":
    #         sha = self.root
    #     if sha is None:
    #         parts = path.rstrip("/").split("/")
    #         so_far = ""
    #         sha = self.root
    #         for part in parts:
    #             out = self.ls(so_far, True, sha=sha)
    #             so_far += "/" + part if so_far else part
    #             out = [o for o in out if o["name"] == so_far][0]
    #             if out["type"] == "file":
    #                 if detail:
    #                     return [out]
    #                 else:
    #                     return path
    #             sha = out["sha"]
    #     if path not in self.dircache:
    #         r = requests.get(self.url.format(org=self.org, repo=self.repo, sha=sha))
    #         self.dircache[path] = [
    #             {
    #                 "name": path + "/" + f["path"] if path else f["path"],
    #                 "mode": f["mode"],
    #                 "type": {"blob": "file", "tree": "directory"}[f["type"]],
    #                 "size": f.get("size", 0),
    #                 "sha": f["sha"],
    #             }
    #             for f in r.json()["tree"]
    #         ]
    #     if detail:
    #         return self.dircache[path]
    #     else:
    #         return sorted([f["name"] for f in self.dircache[path]])
    #
    # def _open_file_id(self, file_id, mode="rb", **kwargs):
    #     request = self.service.files().get_media(fileId=file_id)
    #     data = request.execute()
    #     return io.BytesIO(r.content)
