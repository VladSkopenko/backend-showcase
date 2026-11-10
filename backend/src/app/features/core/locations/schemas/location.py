import uuid

from pydantic import BaseModel, ConfigDict


class LocationCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    address: str
    image_url: str
    table_count: int


class LocationResponse(LocationCardResponse):
    description: str
