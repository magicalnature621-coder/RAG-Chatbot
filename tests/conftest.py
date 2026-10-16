import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Point the app at a throwaway database before any backend module is imported,
# so tests never touch data/college_rag.db.
os.environ["COLLEGE_RAG_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="campusbot_test_"), "test.db")
