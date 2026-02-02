from fastapi import FastAPI

from routes.movies import router


app = FastAPI(
    title="Movies homework",
    description="Description of project"
)

api_version_prefix = "/api/v1"

app.include_router(router, prefix=f"{api_version_prefix}/theater", tags=["theater"])
