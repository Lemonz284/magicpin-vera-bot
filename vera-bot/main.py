from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from api.routes import router
from config import PORT

app = FastAPI(
    title="MagicPin Vera Bot",
    description="Backend AI decision and message composition engine for Vera",
    version="1.0.0"
)

# Allow CORS for test harness flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)
app.include_router(router, prefix="/v1")  # Fallback if evaluation harness appends /v1 to submitted URL ending in /v1


@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "MagicPin Vera AI Bot",
        "endpoints": {
            "health": "/v1/healthz",
            "metadata": "/v1/metadata",
            "documentation": "/docs"
        }
    }


# Global exception handler to prevent unhandled crashes
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error", "error": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
