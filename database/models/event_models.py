from sqlalchemy import Boolean, Column, Date, DateTime, Integer, String, Time, func

from database.session import Base


class DbEvent(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    description = Column(String(), nullable=False, comment="Описание события")
    start_time = Column(Time, nullable=False, comment="Время начала события")
    event_date_pickup = Column(Date, nullable=False, comment="Выбранная дата на календаре")

    single_event = Column(Boolean, nullable=True, comment="Флаг если событие одиночное")
    daily = Column(Boolean, nullable=True, comment="Флаг, если событие ежедневное")
    weekly = Column(Integer, nullable=True, comment="Номер недели, если событие еженедельное")
    monthly = Column(Integer, nullable=True, comment="День, если событие ежемесячное")
    annual_day = Column(Integer, nullable=True, comment="День, если событие ежегодное")
    annual_month = Column(Integer, nullable=True, comment="Месяц, если событие ежегодное")
    stop_time = Column(Time, nullable=True, comment="Время окончания события")

    tg_id = Column(Integer, nullable=False, comment="Юзер тг id, кому принадлежит событие")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
