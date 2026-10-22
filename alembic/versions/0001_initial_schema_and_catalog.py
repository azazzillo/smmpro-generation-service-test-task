"""initial schema and catalog

Revision ID: 0001
Revises:
"""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE users (
            id         bigint PRIMARY KEY,
            balance    bigint NOT NULL DEFAULT 0 CHECK (balance >= 0),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE ledger (
            id         bigserial PRIMARY KEY,
            user_id    bigint NOT NULL REFERENCES users(id),
            delta      bigint NOT NULL CHECK (delta <> 0),
            kind       text   NOT NULL CHECK (kind IN ('grant','payment','charge','refund')),
            ref_id     text   NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ledger_kind_ref_uniq UNIQUE (kind, ref_id)
        )
    """)
    op.execute("CREATE INDEX ledger_user_idx ON ledger (user_id, id DESC)")

    # --- catalog ------------------------------------------------------
    op.execute("""
        CREATE TABLE models (
            slug  text PRIMARY KEY,
            price bigint NOT NULL CHECK (price > 0)
        )
    """)
    op.execute("""
        CREATE TABLE model_legs (
            id                 serial PRIMARY KEY,
            model_slug         text NOT NULL REFERENCES models(slug),
            priority           int  NOT NULL,
            provider           text NOT NULL,
            max_ref_images     int  NOT NULL CHECK (max_ref_images >= 0),
            skip_on_moderation boolean NOT NULL DEFAULT false,
            UNIQUE (model_slug, priority)
        )
    """)

    # --- tasks --------------------------------------------------------
    op.execute("""
        CREATE TABLE tasks (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     bigint NOT NULL REFERENCES users(id),
            model_slug  text   NOT NULL REFERENCES models(slug),
            prompt      text   NOT NULL,
            ref_images  jsonb  NOT NULL DEFAULT '[]',
            price       bigint NOT NULL,           -- цена на момент заказа
            status      text   NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','failed')),
            current_leg_priority int,
            result_url  text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz
        )
    """)
    op.execute("CREATE INDEX tasks_active_idx ON tasks (user_id) WHERE status = 'running'")

    # --- attempts -----------------------------------------------------
    op.execute("""
        CREATE TABLE attempts (
            id          bigserial PRIMARY KEY,
            task_id     uuid NOT NULL REFERENCES tasks(id),
            leg_id      int  NOT NULL REFERENCES model_legs(id),
            provider    text NOT NULL,
            external_id text,
            status      text NOT NULL DEFAULT 'created'
                        CHECK (status IN ('created','sent','completed','failed',
                                          'timeout','late_completed','superseded')),
            error_type  text CHECK (error_type IN ('technical','moderation','payload')),
            created_at  timestamptz NOT NULL DEFAULT now(),
            deadline_at timestamptz NOT NULL,
            finished_at timestamptz,
            -- одну ногу в рамках задачи пробуем не более одного раза:
            -- защита от двойной отправки на следующую ногу
            UNIQUE (task_id, leg_id)
        )
    """)
    op.execute("""
        CREATE UNIQUE INDEX attempts_provider_ext_uniq
        ON attempts (provider, external_id) WHERE external_id IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX attempts_watchdog_idx ON attempts (deadline_at)
        WHERE status IN ('created','sent')
    """)

    # --- payments -----------------------------------------------------
    op.execute("""
        CREATE TABLE payments (
            payment_id text PRIMARY KEY,
            user_id    bigint NOT NULL REFERENCES users(id),
            tokens     bigint NOT NULL CHECK (tokens > 0),
            status     text   NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)

    # --- каталог для старта ------------------------------------------
    op.execute("""
        INSERT INTO models (slug, price) VALUES ('image-fast', 2), ('video-long', 25)
    """)
    op.execute("""
        INSERT INTO model_legs (model_slug, priority, provider, max_ref_images, skip_on_moderation) VALUES
            ('image-fast', 1, 'alpha', 4,  false),
            ('image-fast', 2, 'beta',  10, false),
            ('video-long', 1, 'beta',  2,  false),
            ('video-long', 2, 'alpha', 1,  true)
    """)


def downgrade() -> None:
    for t in ("payments", "attempts", "tasks", "model_legs", "models", "ledger", "users"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")