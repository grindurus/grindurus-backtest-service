from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .models import QueueStatus


class QueueCreate(BaseModel):
    base_asset: str = Field(min_length=1, max_length=32)
    quote_asset: str = Field(min_length=1, max_length=32)
    period_start: datetime
    period_end: datetime
    base_balance_start: Decimal
    quote_balance_start: Decimal
    priority_usdc: Decimal = Field(ge=0)
    creator_address: str = Field(min_length=1)


class QueueItemResponse(BaseModel):
    id: str
    base_asset: str
    quote_asset: str
    period_start: datetime
    period_end: datetime
    base_balance_start: Decimal
    quote_balance_start: Decimal
    priority_usdc: Decimal
    creator_address: str
    status: QueueStatus
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueueStatusUpdate(BaseModel):
    status: QueueStatus


class HistoryCreate(BaseModel):
    base_asset: str = Field(min_length=1, max_length=32)
    quote_asset: str = Field(min_length=1, max_length=32)
    period_start: datetime
    period_end: datetime
    base_balance_start: Decimal
    base_balance_end: Decimal
    quote_balance_start: Decimal
    quote_balance_end: Decimal
    pnl_base: Decimal
    pnl_quote: Decimal
    creator_address: str = Field(min_length=1)


class HistoryItemResponse(BaseModel):
    id: UUID
    base_asset: str
    quote_asset: str
    period_start: datetime
    period_end: datetime
    base_balance_start: Decimal
    base_balance_end: Decimal
    quote_balance_start: Decimal
    quote_balance_end: Decimal
    pnl_base: Decimal
    pnl_quote: Decimal
    creator_address: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PromoCodeAdminResponse(BaseModel):
    code: str
    remaining_uses: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PromoCodeTopUpRequest(BaseModel):
    amount: int = Field(ge=1, description="How many uses to add")


class PromoCodeSetRequest(BaseModel):
    remaining_uses: int = Field(ge=0, description="Absolute remaining uses value")
    is_active: bool = True
