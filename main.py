from fastapi import FastAPI
from db.database import engine
from db import models
from router import user, usage, inventory
from auth import authentication

app = FastAPI()
app.include_router(user.router)
app.include_router(usage.router)
app.include_router(inventory.router)
app.include_router(authentication.router)

@app.get("/")
def root():
    return {"DC Inventory FastAPI Backend"}

models.Base.metadata.create_all(engine)