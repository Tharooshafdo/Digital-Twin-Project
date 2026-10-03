import os
import time
from sqlalchemy.exc import SQLAlchemyError
from tl_twin.storage import Store

store = Store(os.environ["DATABASE_URL"])
for attempt in range(20):
    try:
        store.init()
        print("Schema initialized")
        break
    except SQLAlchemyError:
        if attempt == 19:
            raise
        time.sleep(2)
