# Google Drive fsspec implementation

This is an implementation of the fsspec interface for Google Drive.

This software is in alpha stage and should not be relied upon in production settings.

## Installation

You can install it directly from source using pip:

```sh
pip install git+https://github.com/fsspec/gdrivefs
```

> [!IMPORTANT]
> gdrivefs is *not* released on PyPI. Note that there is a project on PyPI with the name `gdrivefs` which is unrelated and does not implement fsspec. See #21.

## Usage

As gdrivefs implements the fsspec interface, most documentation can be found at https://filesystem-spec.readthedocs.io/en/latest/usage.html.

### Authentication

There are several methods to authenticate gdrivefs against Google Drive.

1. Service account credentials

    In this method, you providea dict containing the service account credentials obtainend in GCP console. The dict content is the same as the json file downloaded from GCP console. More details can be found here: <https://cloud.google.com/iam/docs/service-account-creds#key-types>. This credential can be useful when integrating with other GCP services, and when you don't want the user to be prompted to authenticate.

    ```python
    fs = GoogleDriveFileSystem(creds=service_account_credentials)
    ```

2. OAuth with user credentials

    A browser will be opened to complete the OAuth authentication flow. Afterwards, the access token will be stored locally and you can re-use it in subsequent sessions.

    ```python
    # use this the first time you run
    token = 'browser'
    # use this on subsequent attempts
    #token = 'cache'
    fs = gdrivefs.GoogleDriveFileSystem(token=token)
    ```

3. Anonymous (read-only) access

    If you want to interact with files that are shared publicly ("anyone with the link"), then you do not need to authenticate to Google Drive.

    ```python
    token = 'anon'
    fs = gdrivefs.GoogleDriveFileSystem(token=token)
    ```

See [GoogleDriveFileSystem](https://github.com/fsspec/gdrivefs/blob/master/gdrivefs/core.py#L41) docstring for more details.

## Development

### Running tests

#### Unit tests

```sh
pip install -e . pytest
pytest -v
```

#### Integration tests

To run integration tests, you need to have user credentials cached locally that can be used to interact with your real Google Drive account. You can do this by running the following command:

```py
import gdrivefs
fs = gdrivefs.GoogleDriveFileSystem(token='browser')
print(fs._user_credentials_cache_dir)
```

Alternatively, you can save user credentials in a file and set the environment variable `GDRIVEFS_CREDENTIALS_PATH` to the path of the file.

Then you can run the integration tests:

```sh
pytest -v -m integration
```

## Other implementations

- [PyDrive2](https://github.com/iterative/PyDrive2?tab=readme-ov-file#fsspec-filesystem) also provides an fsspec-compatible Google Drive API.
