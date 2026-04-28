from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base
from settings import settings

engine = create_async_engine(settings.database_url, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _run_compat_migrations(conn)


async def _run_compat_migrations(conn: AsyncConnection) -> None:
    # Keep compatibility with previously created tables that used older columns.
    # We only add missing columns/types and never drop data.
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'queue_status') THEN
                    CREATE TYPE queue_status AS ENUM ('pending', 'processing', 'done', 'failed');
                END IF;
            END
            $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS promocodes (
                code VARCHAR(64) PRIMARY KEY,
                remaining_uses INTEGER NOT NULL DEFAULT 0,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    await conn.execute(
        text(
            """
            INSERT INTO promocodes (code, remaining_uses, is_active)
            VALUES ('GRINDURUS', 100, TRUE)
            ON CONFLICT (code) DO NOTHING
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'period'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN period DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'owner'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN owner DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'base_balance_end'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN base_balance_end DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'quote_balance_end'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN quote_balance_end DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'pnl_base_asset'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN pnl_base_asset DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'pnl_quote_asset'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN pnl_quote_asset DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'payment_address'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN payment_address DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'payment_amount'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN payment_amount DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'payment_token'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN payment_token DROP NOT NULL;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'request_params'
                ) THEN
                    ALTER TABLE backtest_queue ALTER COLUMN request_params DROP NOT NULL;
                END IF;
            END
            $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE backtest_queue
            ALTER COLUMN creator_address TYPE TEXT USING creator_address::TEXT
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue'
                      AND column_name = 'base_balance_start'
                      AND data_type IN ('character varying', 'text')
                ) THEN
                    ALTER TABLE backtest_queue
                    ALTER COLUMN base_balance_start TYPE NUMERIC(38, 18)
                    USING NULLIF(base_balance_start, '')::NUMERIC(38, 18);
                END IF;

                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'backtest_queue'
                      AND column_name = 'quote_balance_start'
                      AND data_type IN ('character varying', 'text')
                ) THEN
                    ALTER TABLE backtest_queue
                    ALTER COLUMN quote_balance_start TYPE NUMERIC(38, 18)
                    USING NULLIF(quote_balance_start, '')::NUMERIC(38, 18);
                END IF;
            END
            $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE backtest_queue
            ADD COLUMN IF NOT EXISTS period_start TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS period_end TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS base_balance_start NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS quote_balance_start NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS priority_usdc NUMERIC(38, 18) DEFAULT 0,
            ADD COLUMN IF NOT EXISTS creator_address TEXT,
            ADD COLUMN IF NOT EXISTS status queue_status DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'backtest_queue' AND column_name = 'owner_address'
                ) THEN
                    UPDATE backtest_queue
                    SET creator_address = COALESCE(creator_address, owner_address)
                    WHERE creator_address IS NULL;
                END IF;
            END
            $$;
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE backtests_history
            ALTER COLUMN creator_address TYPE TEXT USING creator_address::TEXT
            """
        )
    )
    await conn.execute(
        text(
            """
            ALTER TABLE backtests_history
            ADD COLUMN IF NOT EXISTS period_start TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS period_end TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS base_balance_start NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS base_balance_end NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS quote_balance_start NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS quote_balance_end NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS pnl_base NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS pnl_quote NUMERIC(38, 18),
            ADD COLUMN IF NOT EXISTS creator_address TEXT,
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()
            """
        )
    )
    await conn.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'backtests_history' AND column_name = 'owner_address'
                ) THEN
                    UPDATE backtests_history
                    SET creator_address = COALESCE(creator_address, owner_address)
                    WHERE creator_address IS NULL;
                END IF;
            END
            $$;
            """
        )
    )
