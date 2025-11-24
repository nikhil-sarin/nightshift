#!/usr/bin/env python3
"""
Migration: Add allowed_directories column to tasks table

Run this to migrate existing NightShift databases to support sandbox isolation.
"""
import sqlite3
from pathlib import Path
import sys


def migrate_database(db_path: str):
    """Add allowed_directories column to tasks table"""
    db_path = Path(db_path)

    if not db_path.exists():
        print(f"❌ Database not found at: {db_path}")
        sys.exit(1)

    print(f"🔄 Migrating database: {db_path}")

    try:
        with sqlite3.connect(db_path) as conn:
            # Check if column already exists
            cursor = conn.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'allowed_directories' in columns:
                print("✓ Column 'allowed_directories' already exists")
                return

            # Add the new column
            print("  Adding 'allowed_directories' column...")
            conn.execute("""
                ALTER TABLE tasks
                ADD COLUMN allowed_directories TEXT
            """)
            conn.commit()

            print("✅ Migration completed successfully!")
            print("   The 'allowed_directories' column has been added to the tasks table")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    # Default path
    default_db = Path.home() / ".nightshift" / "database" / "nightshift.db"

    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = str(default_db)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  NightShift Database Migration                           ║
║  Adding sandbox isolation support                        ║
╚══════════════════════════════════════════════════════════╝
""")

    migrate_database(db_path)
