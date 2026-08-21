"""pytest 全局配置：在导入 app 之前，把数据库指向临时文件，避免污染真实 lims.db。"""
import os
import sys
import tempfile

# 项目根目录加入 sys.path，确保 `import app` 可用
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 必须在导入 app 前设置，config.DATABASE_URL 在 import 时读取环境变量
_tmp = tempfile.mkdtemp(prefix="lims_test_")
os.environ["LIMS_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["LIMS_SECRET_KEY"] = "test-secret-key"
