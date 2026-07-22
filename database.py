import pymongo, logging
from config import MONGO_URI, DB_NAME
logger = logging.getLogger(__name__)

class Database:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    def __init__(self):
        if self._initialized: return
        self._initialized = True
        self.client = None; self.db = None; self.accounts = None
    def connect(self):
        try:
            self.client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            self.client.admin.command('ping')
            self.db = self.client[DB_NAME]; self.accounts = self.db["accounts"]
            self.accounts.create_index("phone", unique=True, sparse=True)
            self.accounts.create_index("user_id", unique=True, sparse=True)
            self.accounts.create_index("session_string", unique=True)
            logger.info("✅ MongoDB connected"); return True
        except Exception as e: logger.error(f"❌ MongoDB: {e}"); return False
    def disconnect(self):
        if self.client: self.client.close()

db = Database()
