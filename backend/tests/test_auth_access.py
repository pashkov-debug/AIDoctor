from collections.abc import Generator
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from app.db.base import Base
from app.db.session import create_database_engine, get_db
from app.main import app
from app.core.security import hash_password
from app.models.access import User, DoctorPatient
from app.models.patient import Patient

def test_roles_and_boundaries(tmp_path: Path):
    engine = create_database_engine(f"sqlite+pysqlite:///{tmp_path/'roles.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        doc = User(username="doctor1", password_hash=hash_password("very-strong-password"), role="doctor")
        other = User(username="doctor2", password_hash=hash_password("very-strong-password"), role="doctor")
        patient_account = User(username="patient1", password_hash=hash_password("very-strong-password"), role="patient")
        db.add_all([doc,other,patient_account]);db.flush()
        p1 = Patient(alias="P-1", demographics_json={}, user_id=patient_account.id)
        p2 = Patient(alias="P-2", demographics_json={})
        db.add_all([p1,p2]);db.flush()
        db.add(DoctorPatient(doctor_id=doc.id,patient_id=p1.id))
        ids=(p1.id,p2.id)
        db.commit()
    def override():
        with factory() as db: yield db
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            assert client.get(f"/api/v1/patients/{ids[0]}").status_code == 401
            bad=client.post("/api/v1/auth/login",json={"username":"doctor1","password":"wrong"})
            assert bad.status_code == 401
            def login(username):
                r=client.post("/api/v1/auth/login",json={"username":username,"password":"very-strong-password"})
                assert r.status_code == 200, r.text
                return {"Authorization":"Bearer "+r.json()["access_token"]}
            doctor=login("doctor1")
            outsider=login("doctor2")
            patient=login("patient1")
            assert client.get(f"/api/v1/patients/{ids[0]}",headers=doctor).status_code == 200
            assert client.get(f"/api/v1/patients/{ids[1]}",headers=doctor).status_code == 404
            assert client.get(f"/api/v1/patients/{ids[0]}",headers=outsider).status_code == 404
            assert client.get(f"/api/v1/patients/{ids[0]}",headers=patient).status_code == 200
            assert client.get(f"/api/v1/patients/{ids[1]}",headers=patient).status_code == 404
            assert client.post("/api/v1/patients",headers=patient,json={"alias":"bad","demographics":{}}).status_code == 403
            assert client.get("/api/v1/patients",headers=doctor).json()["total"] == 1
            assert client.get("/api/v1/patients",headers=outsider).json()["total"] == 0
            assert client.post("/api/v1/access/link",headers=doctor,json={"doctor_id":"x","patient_id":"y"}).status_code == 403
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
