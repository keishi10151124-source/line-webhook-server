"""File storage: local folder for development, Cloudflare R2 (S3 API) for production."""
import shutil
from datetime import timedelta
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("bad key")
        return p

    def put_file(self, key: str, src: str | Path) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, p)

    def put_bytes(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_to_file(self, key: str, dest: str | Path) -> None:
        shutil.copyfile(self._path(key), dest)

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def url(self, key: str, expires: timedelta = timedelta(minutes=15)) -> str | None:
        return None  # served by the app in development


class R2Storage:
    def __init__(self, endpoint: str, bucket: str, key_id: str, secret: str):
        import boto3

        self.bucket = bucket
        self.s3 = boto3.client(
            "s3", endpoint_url=endpoint, aws_access_key_id=key_id,
            aws_secret_access_key=secret, region_name="auto",
        )

    def put_file(self, key, src):
        self.s3.upload_file(str(src), self.bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})

    def put_bytes(self, key, data):
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ServerSideEncryption="AES256")

    def get_to_file(self, key, dest):
        self.s3.download_file(self.bucket, key, str(dest))

    def get_bytes(self, key):
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.s3.delete_object(Bucket=self.bucket, Key=key)

    def local_path(self, key):
        return None

    def url(self, key, expires=timedelta(minutes=15)):
        return self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=int(expires.total_seconds())
        )


def make_storage(cfg):
    if cfg.STORAGE == "r2":
        return R2Storage(cfg.R2_ENDPOINT, cfg.R2_BUCKET, cfg.R2_ACCESS_KEY_ID, cfg.R2_SECRET_ACCESS_KEY)
    return LocalStorage(cfg.LOCAL_STORAGE_DIR)
