"""
database.py - MongoDB connection and collection setup for the Telegram Account Manager.
"""
import pymongo
import logging
from config import MONGO_URI, DB_NAME

logger = logging.getLogger(__name__)


class Database:
    """Singleton MongoDB handler."""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.client = None
        self.db = None
        self.accounts = None
        self.joins = None
        self.operations = None
    
    def connect(self):
        """Connect to MongoDB."""
        try:
            self.client = pymongo.MongoClient(
                MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            # Ping to verify connection
            self.client.admin.command('ping')
            self.db = self.client[DB_NAME]
            self.accounts = self.db["accounts"]
            self.joins = self.db["joins"]
            self.operations = self.db["operations"]
            
            # Create indexes
            self.accounts.create_index("phone", unique=True, sparse=True)
            self.accounts.create_index("user_id", unique=True, sparse=True)
            self.accounts.create_index("session_string", unique=True)
            
            logger.info("✅ Connected to MongoDB successfully")
            return True
        except pymongo.errors.ConnectionFailure as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ MongoDB error: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from MongoDB."""
        if self.client:
            self.client.close()
            logger.info("Disconnected from MongoDB")


# Global database instance
db = Database()
