"""待审列表。这个接口不发送消息。"""

from kefu_offline.review_store import ReviewStore


def list_reviews() -> dict:
    return {
        "send_allowed": False,
        "transport_send": False,
        "reviews": ReviewStore().list_records(),
    }


try:
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/api/kefu/reviews")
    def get_reviews():
        return list_reviews()
except Exception:  # pragma: no cover - fastapi 未安装时仍保留列表函数
    router = None
