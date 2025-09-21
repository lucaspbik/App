from datetime import datetime

import pytest

from waren_eingang import create_app, get_db, init_db


@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "test.sqlite"
    app = create_app({"TESTING": True, "DATABASE": str(db_path)})
    with app.app_context():
        init_db()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def test_create_delivery(client, app):
    response = client.post(
        "/deliveries/new",
        data={
            "supplier": "Bosch Rexroth",
            "delivery_note": "LS-1001",
            "purchase_order": "PO-9001",
            "part_number": "MRP-200",
            "part_description": "Hydraulikventil",
            "quantity_expected": "12",
            "quantity_received": "10",
            "unit": "Stk",
            "inspection_required": "on",
            "certificate_received": "on",
            "priority": "hoch",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Wareneingang erfolgreich erfasst" in response.data

    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT * FROM deliveries WHERE supplier = ?", ("Bosch Rexroth",)
        ).fetchone()
        assert row is not None
        assert row["quantity_expected"] == 12
        assert row["certificate_received"] == 1
        assert row["status"] == "registered"


def test_update_delivery(client, app):
    with app.app_context():
        db = get_db()
        db.execute(
            """
            INSERT INTO deliveries (
                supplier, delivery_note, purchase_order, part_number,
                part_description, quantity_expected, quantity_received,
                unit, inspection_required, certificate_received, status,
                priority, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "DMG Mori",
                "LS-900",
                "PO-42",
                "SP-100",
                "Spindel",
                5,
                5,
                "Stk",
                1,
                0,
                "registered",
                "normal",
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        delivery_id = db.execute(
            "SELECT id FROM deliveries WHERE supplier = ?", ("DMG Mori",)
        ).fetchone()["id"]
        db.commit()

    response = client.post(
        f"/deliveries/{delivery_id}/inspect",
        data={
            "status": "accepted",
            "inspector": "QS-Meyer",
            "quantity_received": "5",
            "storage_location": "HB-01-03",
            "comments": "Maße innerhalb Toleranz",
            "next_action": "Einlagerung",
            "certificate_received": "on",
            "priority": "hoch",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Wareneingang aktualisiert" in response.data

    with app.app_context():
        db = get_db()
        row = db.execute(
            "SELECT * FROM deliveries WHERE id = ?", (delivery_id,)
        ).fetchone()
        assert row["status"] == "accepted"
        assert row["inspector"] == "QS-Meyer"
        assert row["storage_location"] == "HB-01-03"
        assert row["certificate_received"] == 1
