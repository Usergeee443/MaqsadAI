from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
from enum import Enum

class TariffType(Enum):
    FREE = "FREE"
    PRO = "PRO"
    MAX = "MAX"

class TransactionType(Enum):
    INCOME = "income"
    EXPENSE = "expense"
    DEBT = "debt"

@dataclass
class User:
    user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    tariff: TariffType
    created_at: datetime
    is_active: bool = True

@dataclass
class Transaction:
    id: Optional[int]
    user_id: int
    amount: float
    category: str
    description: Optional[str]
    transaction_type: TransactionType
    created_at: datetime

@dataclass
class Todo:
    id: Optional[int]
    user_id: int
    title: str
    description: Optional[str]
    due_date: Optional[datetime]
    created_at: datetime
    is_completed: bool = False

@dataclass
class Goal:
    id: Optional[int]
    user_id: int
    title: str
    description: str
    target_amount: Optional[float]
    target_date: Optional[datetime]
    created_at: datetime
    current_progress: float = 0.0
    is_active: bool = True

@dataclass
class DailyTask:
    id: Optional[int]
    goal_id: int
    task: str
    due_date: datetime
    created_at: datetime
    is_completed: bool = False
