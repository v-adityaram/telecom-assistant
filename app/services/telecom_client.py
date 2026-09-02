import logging
import ssl

import httpx
import truststore
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger("telecom_assistant.telecom_client")

TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=3.0, pool=3.0)

# Uses the OS certificate store (via truststore) instead of certifi's bundle,
# since networks with TLS-inspecting proxies re-sign traffic with a corporate
# root CA that Windows trusts but certifi does not.
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class ToolResult(BaseModel):
    success: bool
    data: dict | None = None
    error: str | None = None
    status_code: int | None = None


async def get_json(path: str, mobile_number: str) -> ToolResult:
    settings = get_settings()
    url = f"{settings.telecom_api_base_url}{path}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, verify=SSL_CONTEXT) as client:
            response = await client.get(url, params={"mobileNumber": mobile_number})
        response.raise_for_status()
        return ToolResult(success=True, data=response.json(), status_code=response.status_code)

    except httpx.TimeoutException:
        logger.warning("telecom_api_timeout path=%s", path)
        return ToolResult(success=False, error="telecom_api_timeout")

    except httpx.HTTPStatusError as exc:
        logger.warning("telecom_api_http_error path=%s status=%s", path, exc.response.status_code)
        return ToolResult(
            success=False,
            error="telecom_api_error",
            status_code=exc.response.status_code,
        )

    except httpx.RequestError:
        logger.warning("telecom_api_request_error path=%s", path)
        return ToolResult(success=False, error="telecom_api_unreachable")

    except ValueError:
        logger.warning("telecom_api_invalid_response path=%s", path)
        return ToolResult(success=False, error="telecom_api_invalid_response")
