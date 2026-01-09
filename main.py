import time

from fastapi import Body, FastAPI
from fastapi.responses import JSONResponse

from sentiment_analyzer import BusinessRuleError, ValidationError, analyze_feed


app = FastAPI()


@app.post("/analyze-feed")
def analyze_feed_endpoint(payload: dict = Body(...)) -> JSONResponse:
    start = time.perf_counter()
    try:
        analysis = analyze_feed(payload)
    except BusinessRuleError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": exc.message, "code": exc.code},
        )
    except ValidationError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": exc.message, "code": exc.code},
        )

    analysis["processing_time_ms"] = int((time.perf_counter() - start) * 1000)
    return JSONResponse(content={"analysis": analysis})
