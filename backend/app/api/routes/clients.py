from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError, conflict
from app.db.models import Client, Project, User
from app.db.session import get_db
from app.schemas.projects import ClientIn, ClientOut, ClientUpdate
from app.services.projects import get_owned_client

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[Client]:
    return list(db.execute(select(Client).where(Client.owner_id == user.id).order_by(Client.name)).scalars())


@router.post("", status_code=201, response_model=ClientOut)
def create_client(
    body: ClientIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Client:
    client = Client(owner_id=user.id, **body.model_dump())
    client.name = client.name.strip()
    db.add(client)
    db.commit()
    return client


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: UUID, body: ClientUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Client:
    client = get_owned_client(db, user.id, client_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise AppError(422, "validation_error", "name cannot be empty", {"fields": ["name"]})
    for field, value in changes.items():
        setattr(client, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return client


@router.delete("/{client_id}", status_code=204, response_class=Response)
def delete_client(
    client_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    client = get_owned_client(db, user.id, client_id)
    if db.execute(select(exists().where(Project.client_id == client.id))).scalar():
        raise conflict("client_in_use", "the client is used by projects")
    db.delete(client)
    db.commit()
