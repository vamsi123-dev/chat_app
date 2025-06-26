from pydantic import BaseSettings

class Settings(BaseSettings):
    SQLALCHEMY_DATABASE_URL: str = "mysql+pymysql://app_user_vamsi:chatvamsi123@localhost:3306/final_db_vamsi"
    SECRET_KEY: str = "supersecretkey"  # Change to a secure value in production
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

settings = Settings() 