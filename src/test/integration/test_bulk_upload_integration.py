"""
Integration tests for the bulk upload missions feature.

Uses in-memory SQLite + TestClient(app) + mocked external services.
"""
from __future__ import annotations

import io
import csv
import json
import zipfile
import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import patch, AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from src.ecommerce.api.main import app
from src.shared.db.database import Base, get_db
from src.ecommerce.db.models import Plan, User, Shop
from src.agentic_core.db.models import Mission
from src.shared.security.security import verify_shopify_session
from src.ecommerce.api.shopify.shared import resolve_shop_domain


TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SHOP_DOMAIN = "bulk-test.myshopify.com"


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_resolve_shop_domain():
    return SHOP_DOMAIN


# ── Helpers ──────────────────────────────────────────────────────────────────

REQUIRED_COLS = ["row_id", "product_name_ja", "description_ja", "category", "target_market"]


def _csv_bytes(n_rows: int = 3, extra_cols: Optional[dict] = None) -> bytes:
    cols = list(REQUIRED_COLS)
    if extra_cols:
        cols.extend(extra_cols.keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for i in range(1, n_rows + 1):
        row = {
            "row_id": f"r{i}",
            "product_name_ja": f"商品{i}",
            "description_ja": f"説明{i}",
            "category": "General",
            "target_market": "en",
        }
        if extra_cols:
            row.update({k: v.format(i=i) if isinstance(v, str) else v for k, v in extra_cols.items()})
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _zip_bytes(n_rows: int = 3) -> bytes:
    csv_data = _csv_bytes(n_rows, extra_cols={"image_ref": "img_{i}.jpg"})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("products.csv", csv_data.decode("utf-8"))
        for i in range(1, n_rows + 1):
            zf.writestr(f"images/img_{i}.jpg", b"\xff\xd8\xff\xe0fake-jpeg")
    return buf.getvalue()


def _payload(mission_type: str = "text_only") -> str:
    return json.dumps({
        "mission_type": mission_type,
        "preferences": {
            "tone_profile": "professional",
            "brand_soul_enabled": False,
            "us_units_conversion": True,
            "target_market": "en",
        },
    })


def _seed_shop(plan_name: str = "Pro", image_credits_used: int = 0):
    db = TestingSessionLocal()
    db.query(User).delete()
    db.query(Shop).delete()
    db.query(Plan).delete()
    db.query(Mission).delete()
    db.commit()

    plan = Plan(name=plan_name, monthly_rewrite_limit=1000, max_request_rate=100, can_stream_responses=True)
    db.add(plan)
    db.commit()

    user = User(username=SHOP_DOMAIN, plan_id=plan.id)
    db.add(user)
    db.commit()

    now = datetime.now(timezone.utc)
    db.add(Shop(
        domain=SHOP_DOMAIN,
        access_token="test-token",
        monthly_rewrites_used=0,
        reset_anchor_date=now,
        next_reset_date=now + timedelta(days=30),
        current_plan_name=plan_name,
        last_plan_name=plan_name,
        access_expires_at=now + timedelta(days=30),
        monthly_missions_used=0,
        monthly_image_generations_used=image_credits_used,
    ))
    db.commit()
    db.close()


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    """Ensure all tables exist for the entire test module."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="module")
def client(_create_tables):
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[resolve_shop_domain] = override_resolve_shop_domain
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    del app.dependency_overrides[get_db]
    del app.dependency_overrides[resolve_shop_domain]


# ── Tests ────────────────────────────────────────────────────────────────────


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_text_only_full_lifecycle(mock_create_task, client):
    """Text-only CSV -> 3 child missions with correct workflow."""
    _seed_shop("Pro")
    csv_data = _csv_bytes(3)

    resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", csv_data, "text/csv")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert "bulk_mission_id" in body
    assert len(body["child_mission_ids"]) == 3
    assert body["total"] == 3

    # Verify DB state
    db = TestingSessionLocal()
    parent = db.query(Mission).filter(Mission.id == body["bulk_mission_id"]).first()
    assert parent is not None
    assert parent.status == "IN_PROGRESS"
    state = parent.current_state
    assert state["is_bulk_parent"] is True
    assert state["total"] == 3

    children = db.query(Mission).filter(Mission.bulk_mission_id == body["bulk_mission_id"]).all()
    assert len(children) == 3
    for child in children:
        assert child.status == "PENDING"
        child_state = child.current_state
        assert child_state["workflow_agents"] == ["RewriterAgent", "SEOAgent"]

    # Verify mission counter incremented
    shop = db.query(Shop).filter(Shop.domain == SHOP_DOMAIN).first()
    assert shop.monthly_missions_used == 3
    db.close()


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
@patch("src.ecommerce.services.r2_storage_service.R2StorageService.upload_asset", new_callable=AsyncMock, return_value="https://r2.example.com/img.png")
def test_full_launch_lifecycle(mock_r2, mock_create_task, client):
    """Full-launch ZIP -> child missions with ImageRefinement in workflow."""
    _seed_shop("Pro", image_credits_used=0)
    zip_data = _zip_bytes(5)

    resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("full_launch")},
        files={"file": ("upload.zip", zip_data, "application/zip")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["child_mission_ids"]) == 5

    db = TestingSessionLocal()
    children = db.query(Mission).filter(Mission.bulk_mission_id == body["bulk_mission_id"]).all()
    for child in children:
        child_state = child.current_state
        assert child_state["workflow_agents"] == ["RewriterAgent", "ImageRefinementAgent", "SEOAgent"]
        assert child_state["raw_input"].get("image_url") is not None
    db.close()


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_plan_gating_non_pro_rejected(mock_create_task, client):
    """Standard plan -> 403 for bulk upload."""
    _seed_shop("Standard")
    csv_data = _csv_bytes(2)

    resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", csv_data, "text/csv")},
    )

    assert resp.status_code == 403
    assert "Pro" in resp.json()["detail"]


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_image_credit_preflight_insufficient(mock_create_task, client):
    """Pro shop with only 3 remaining image credits -> 422 for 5-product full_launch."""
    _seed_shop("Pro", image_credits_used=97)  # 100 - 97 = 3 remaining
    zip_data = _zip_bytes(5)

    resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("full_launch")},
        files={"file": ("upload.zip", zip_data, "application/zip")},
    )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert "5" in detail
    assert "3" in detail


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_max_products_exceeded(mock_create_task, client):
    """CSV with 12 rows -> 422."""
    _seed_shop("Pro")
    csv_data = _csv_bytes(12)

    resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", csv_data, "text/csv")},
    )

    assert resp.status_code == 422
    assert "Maximum" in resp.json()["detail"]


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_invalid_csv_missing_columns(mock_create_task, client):
    """CSV missing description_ja -> 422."""
    _seed_shop("Pro")
    bad_csv = b"row_id,product_name_ja,category,target_market\n1,A,B,en\n"

    resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", bad_csv, "text/csv")},
    )

    assert resp.status_code == 422
    assert "description_ja" in resp.json()["detail"]


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_bulk_status_endpoint_in_progress(mock_create_task, client):
    """Status endpoint returns progress for in-progress parent mission."""
    _seed_shop("Pro")
    csv_data = _csv_bytes(5)

    create_resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", csv_data, "text/csv")},
    )
    bulk_id = create_resp.json()["bulk_mission_id"]

    # Manually update parent to simulate partial progress
    db = TestingSessionLocal()
    parent = db.query(Mission).filter(Mission.id == bulk_id).first()
    state = dict(parent.current_state)
    state["completed"] = 3
    state["failed"] = 0
    parent.current_state = state
    db.add(parent)
    db.commit()
    db.close()

    status_resp = client.get(f"/api/missions/bulk/{bulk_id}/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "IN_PROGRESS"
    assert body["total"] == 5
    assert body["completed"] == 3
    assert body["failed"] == 0


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_bulk_status_endpoint_completed(mock_create_task, client):
    """Status endpoint returns shop_products_url when completed."""
    _seed_shop("Pro")
    csv_data = _csv_bytes(3)

    create_resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", csv_data, "text/csv")},
    )
    bulk_id = create_resp.json()["bulk_mission_id"]

    # Simulate completion
    db = TestingSessionLocal()
    parent = db.query(Mission).filter(Mission.id == bulk_id).first()
    parent.status = "COMPLETED"
    state = dict(parent.current_state)
    state["completed"] = 3
    state["failed"] = 0
    parent.current_state = state
    db.add(parent)
    db.commit()
    db.close()

    status_resp = client.get(f"/api/missions/bulk/{bulk_id}/status")
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == "COMPLETED"
    assert body["total"] == 3
    assert body["completed"] == 3
    assert "shop_products_url" in body
    assert "bulk-test" in body["shop_products_url"]


@pytest.mark.asyncio
@patch("src.ecommerce.services.shopify_service.create_product_in_shopify", new_callable=AsyncMock, return_value="gid://shopify/Product/999")
@patch("src.ecommerce.db.transactions.get_shop_access_token", return_value="mock-token")
async def test_background_task_execution(mock_token, mock_create_prod):
    """Background task runs all children and creates Shopify products."""
    from src.ecommerce.api.shopify.missions import _run_bulk_mission_background

    _seed_shop("Pro")
    db = TestingSessionLocal()

    # Create parent + children manually
    parent_id = "bg-test-parent"
    child_ids = ["bg-child-1", "bg-child-2"]

    parent = Mission(
        id=parent_id,
        shop_id=SHOP_DOMAIN,
        product_id="bulk",
        status="IN_PROGRESS",
        current_state={
            "is_bulk_parent": True,
            "mission_type": "text_only",
            "total": 2,
            "completed": 0,
            "failed": 0,
            "image_credits_used": 0,
            "child_ids": child_ids,
        },
        plan_tier="Pro",
    )
    db.add(parent)

    for cid in child_ids:
        child = Mission(
            id=cid,
            shop_id=SHOP_DOMAIN,
            product_id=f"row-{cid}",
            status="PENDING",
            current_state={
                "product_id": f"row-{cid}",
                "shop_id": SHOP_DOMAIN,
                "plan_tier": "Pro",
                "raw_input": {
                    "product_id": f"row-{cid}",
                    "title": "Test",
                    "product_name": "Test",
                    "description": "Desc",
                    "japanese_description": "説明",
                    "category": "General",
                    "tone": "professional",
                    "target_locale": "en",
                },
                "target_locale": "en",
                "status": "PENDING",
                "logs": [],
                "current_agent_index": 0,
                "skipped_agents": [],
                "agent_outputs": {},
                "workflow_agents": ["RewriterAgent", "SEOAgent"],
                "workflow_config": [
                    {"agent_name": "RewriterAgent", "has_gate": False},
                    {"agent_name": "SEOAgent", "has_gate": False},
                ],
                "autonomous": True,
            },
            plan_tier="Pro",
            bulk_mission_id=parent_id,
        )
        db.add(child)
    db.commit()
    db.close()

    # Mock MissionControl.execute and SessionLocal
    mock_state = MagicMock()
    mock_state.status = "COMPLETED"
    mock_state.draft_title = "Rewritten Title"
    mock_state.draft_content = "<p>Rewritten</p>"
    mock_state.seo_title = "SEO Title"
    mock_state.seo_description = "SEO Desc"
    mock_state.seo_alt_text = ""
    mock_state.visual_assets = {}
    mock_state.error_message = None
    mock_state.to_dict.return_value = {"status": "COMPLETED", "raw_input": {"category": "General"}}
    mock_state.logs = []

    async def mock_execute(state):
        yield mock_state

    mc_instance = MagicMock()
    mc_instance.execute = mock_execute

    MockMC = MagicMock(return_value=mc_instance)
    MockSR = MagicMock()
    mock_from_dict = MagicMock(return_value=MagicMock(mission_id=None))

    with patch("src.shared.db.database.SessionLocal", return_value=TestingSessionLocal()), \
         patch("src.ecommerce.orchestrator.MissionControl", MockMC), \
         patch("src.ecommerce.orchestrator.MissionState") as MockMS, \
         patch("src.ecommerce.services.ServiceRegistry", MockSR):

        MockMS.from_dict = mock_from_dict

        await _run_bulk_mission_background(
            parent_id=parent_id,
            child_ids=child_ids,
            shop_domain=SHOP_DOMAIN,
            plan_tier="Pro",
            mission_type="text_only",
        )

    # Verify results
    db = TestingSessionLocal()
    parent = db.query(Mission).filter(Mission.id == parent_id).first()
    assert parent.status == "COMPLETED"
    assert parent.current_state["completed"] == 2
    assert parent.current_state["failed"] == 0

    for cid in child_ids:
        child = db.query(Mission).filter(Mission.id == cid).first()
        assert child.status == "COMPLETED"

    assert mock_create_prod.call_count == 2
    db.close()


@pytest.mark.asyncio
@patch("src.ecommerce.services.shopify_service.create_product_in_shopify", new_callable=AsyncMock)
@patch("src.ecommerce.db.transactions.get_shop_access_token", return_value="mock-token")
async def test_background_task_partial_failure(mock_token, mock_create_prod):
    """Background task handles partial failure gracefully."""
    from src.ecommerce.api.shopify.missions import _run_bulk_mission_background

    _seed_shop("Pro")
    db = TestingSessionLocal()

    parent_id = "partial-fail-parent"
    child_ids = ["pf-child-1", "pf-child-2", "pf-child-3"]

    parent = Mission(
        id=parent_id,
        shop_id=SHOP_DOMAIN,
        product_id="bulk",
        status="IN_PROGRESS",
        current_state={
            "is_bulk_parent": True,
            "mission_type": "text_only",
            "total": 3,
            "completed": 0,
            "failed": 0,
            "image_credits_used": 0,
            "child_ids": child_ids,
        },
        plan_tier="Pro",
    )
    db.add(parent)

    for cid in child_ids:
        child = Mission(
            id=cid,
            shop_id=SHOP_DOMAIN,
            product_id=f"row-{cid}",
            status="PENDING",
            current_state={
                "product_id": f"row-{cid}",
                "shop_id": SHOP_DOMAIN,
                "plan_tier": "Pro",
                "raw_input": {
                    "product_id": f"row-{cid}",
                    "title": "Test",
                    "product_name": "Test",
                    "description": "Desc",
                    "japanese_description": "説明",
                    "category": "General",
                    "tone": "professional",
                    "target_locale": "en",
                },
                "target_locale": "en",
                "status": "PENDING",
                "logs": [],
                "current_agent_index": 0,
                "skipped_agents": [],
                "agent_outputs": {},
                "workflow_agents": ["RewriterAgent", "SEOAgent"],
                "workflow_config": [
                    {"agent_name": "RewriterAgent", "has_gate": False},
                    {"agent_name": "SEOAgent", "has_gate": False},
                ],
                "autonomous": True,
            },
            plan_tier="Pro",
            bulk_mission_id=parent_id,
        )
        db.add(child)
    db.commit()
    db.close()

    call_count = [0]

    mock_ok_state = MagicMock()
    mock_ok_state.status = "COMPLETED"
    mock_ok_state.draft_title = "Title"
    mock_ok_state.draft_content = "<p>Content</p>"
    mock_ok_state.seo_title = "SEO"
    mock_ok_state.seo_description = "SEO Desc"
    mock_ok_state.seo_alt_text = ""
    mock_ok_state.visual_assets = {}
    mock_ok_state.error_message = None
    mock_ok_state.to_dict.return_value = {"status": "COMPLETED", "raw_input": {"category": "General"}}
    mock_ok_state.logs = []

    mock_err_state = MagicMock()
    mock_err_state.status = "ERROR"
    mock_err_state.error_message = "Agent failed"
    mock_err_state.to_dict.return_value = {"status": "ERROR"}
    mock_err_state.logs = []

    async def mock_execute(state):
        call_count[0] += 1
        if call_count[0] == 2:
            yield mock_err_state
        else:
            yield mock_ok_state

    mc_instance = MagicMock()
    mc_instance.execute = mock_execute
    MockMC = MagicMock(return_value=mc_instance)
    MockSR = MagicMock()
    mock_from_dict = MagicMock(return_value=MagicMock(mission_id=None))

    mock_create_prod.return_value = "gid://shopify/Product/999"

    with patch("src.shared.db.database.SessionLocal", return_value=TestingSessionLocal()), \
         patch("src.ecommerce.orchestrator.MissionControl", MockMC), \
         patch("src.ecommerce.orchestrator.MissionState") as MockMS, \
         patch("src.ecommerce.services.ServiceRegistry", MockSR):

        MockMS.from_dict = mock_from_dict

        await _run_bulk_mission_background(
            parent_id=parent_id,
            child_ids=child_ids,
            shop_domain=SHOP_DOMAIN,
            plan_tier="Pro",
            mission_type="text_only",
        )

    db = TestingSessionLocal()
    parent = db.query(Mission).filter(Mission.id == parent_id).first()
    assert parent.status == "COMPLETED"
    assert parent.current_state["completed"] == 2
    assert parent.current_state["failed"] == 1

    child_2 = db.query(Mission).filter(Mission.id == "pf-child-2").first()
    assert child_2.status == "ERROR"

    child_1 = db.query(Mission).filter(Mission.id == "pf-child-1").first()
    assert child_1.status == "COMPLETED"

    child_3 = db.query(Mission).filter(Mission.id == "pf-child-3").first()
    assert child_3.status == "COMPLETED"
    db.close()


@patch("src.ecommerce.api.shopify.missions.asyncio.create_task")
def test_bulk_missions_in_history(mock_create_task, client):
    """Bulk parent missions appear in mission history list."""
    _seed_shop("Pro")
    csv_data = _csv_bytes(2)

    create_resp = client.post(
        "/api/missions/bulk",
        data={"payload": _payload("text_only")},
        files={"file": ("products.csv", csv_data, "text/csv")},
    )
    assert create_resp.status_code == 200

    # Get mission list
    bulk_id = create_resp.json()["bulk_mission_id"]
    list_resp = client.get("/api/missions")
    assert list_resp.status_code == 200
    missions = list_resp.json()["missions"]

    # Parent should appear with is_bulk_parent=True
    parent_missions = [
        m for m in missions
        if m.get("mission_title") and "Bulk" in m["mission_title"]
    ]
    assert len(parent_missions) >= 1
    assert "2 products" in parent_missions[0]["mission_title"]
    assert parent_missions[0]["is_bulk_parent"] is True

    # Child missions should NOT appear in the list
    child_ids = set(create_resp.json()["child_mission_ids"])
    listed_ids = {m["id"] for m in missions}
    assert child_ids.isdisjoint(listed_ids), "Child missions should be filtered from history"
