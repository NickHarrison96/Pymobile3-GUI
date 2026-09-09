# =============================================================================
# Pymobile3-GUI — iOS AFC File System Core Service
# =============================================================================

import os
import threading
import inspect

class AFCException(Exception):
    pass


class FileSystemManager:
    """
    AFC (Apple File Conduit) wrapper providing directory browsing, file read/write,
    deletion, directory creation, and upload/download.
    """

    def __init__(self, lockdown_provider=None):
        self._lockdown_provider = lockdown_provider
        self._afc = None
        self._lock = threading.Lock()

    def _resolve(self, result):
        if inspect.iscoroutine(result):
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(result)
            return loop.run_until_complete(result)
        return result

    def _get_afc(self):
        with self._lock:
            if self._afc:
                return self._afc

            try:
                from pymobiledevice3.services.afc import AfcService
                if self._lockdown_provider is None:
                    from pymobiledevice3.lockdown import create_using_usbmux
                    lockdown = create_using_usbmux()
                    if inspect.iscoroutine(lockdown):
                        lockdown = self._resolve(lockdown)
                else:
                    lockdown = self._lockdown_provider

                if not lockdown:
                    raise AFCException("No iOS lockdown connection available.")

                afc = AfcService(lockdown)
                if inspect.iscoroutine(afc):
                    afc = self._resolve(afc)
                self._afc = afc
                return self._afc
            except AFCException:
                raise
            except Exception as e:
                raise AFCException(f"Failed to initialize AFC service: {e}")

    def list_dir(self, path="/"):
        afc = self._get_afc()
        try:
            res = afc.listdir(path)
            return self._resolve(res)
        except AFCException:
            raise
        except Exception as e:
            raise AFCException(f"list_dir failed for '{path}': {e}")

    def is_dir(self, path):
        try:
            self.list_dir(path)
            return True
        except AFCException:
            return False

    def read_file(self, path):
        afc = self._get_afc()
        try:
            res = afc.get_file_contents(path)
            return self._resolve(res)
        except AFCException:
            raise
        except Exception as e:
            raise AFCException(f"read_file failed: {e}")

    def write_file(self, path, data_bytes):
        afc = self._get_afc()
        try:
            res = afc.set_file_contents(path, data_bytes)
            return self._resolve(res)
        except AFCException:
            raise
        except Exception as e:
            raise AFCException(f"write_file failed: {e}")

    def make_dir(self, path):
        afc = self._get_afc()
        try:
            res = afc.mkdir(path)
            return self._resolve(res)
        except AFCException:
            raise
        except Exception as e:
            raise AFCException(f"make_dir failed: {e}")

    def remove(self, path):
        afc = self._get_afc()
        try:
            res = afc.rm(path)
            return self._resolve(res)
        except AFCException:
            raise
        except Exception as e:
            raise AFCException(f"remove failed: {e}")

    def download_file(self, remote_path, local_path):
        data = self.read_file(remote_path)
        parent_dir = os.path.dirname(local_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return local_path

    def upload_file(self, local_path, remote_path):
        with open(local_path, "rb") as f:
            data = f.read()
        return self.write_file(remote_path, data)
