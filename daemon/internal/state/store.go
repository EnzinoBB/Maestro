package state

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("component not found")

// Component represents the last known local state of a component.
type Component struct {
	ID            string
	Status        string
	ComponentHash string
	Runner        string
	PID           int
	ContainerID   string
	ContainerName string
	StartedAt     *time.Time
	LastHCAt      *time.Time
	LastHCOK      bool
	UnitName      string
	WorkDir       string
}

type HistoryEntry struct {
	ID            int64
	ComponentID   string
	ComponentHash string
	TS            time.Time
}

type Store interface {
	Close() error
	Get(ctx context.Context, id string) (*Component, error)
	Upsert(ctx context.Context, c *Component) error
	List(ctx context.Context) ([]*Component, error)
	Delete(ctx context.Context, id string) error
	AppendHistory(ctx context.Context, componentID, hash string) error
	History(ctx context.Context, componentID string, limit int) ([]HistoryEntry, error)
}

type sqliteStore struct {
	db *sql.DB
}

const schema = `
CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'unknown',
    component_hash TEXT,
    runner TEXT,
    pid INTEGER,
    container_id TEXT,
    container_name TEXT,
    started_at TEXT,
    last_hc_at TEXT,
    last_hc_ok INTEGER,
    unit_name TEXT,
    work_dir TEXT
);
-- best-effort add-column for existing installations
ALTER TABLE components ADD COLUMN container_name TEXT;
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id TEXT NOT NULL,
    component_hash TEXT,
    ts TEXT NOT NULL
);
`

// Open creates or opens a SQLite store at path.
func Open(path string) (Store, error) {
	if path == "" {
		return nil, fmt.Errorf("empty store path")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", path+"?_pragma=journal_mode(WAL)")
	if err != nil {
		return nil, err
	}
	// Execute schema statements one at a time, ignoring "duplicate column"
	// errors from ALTER TABLE on existing databases.
	stmts := []string{
		`CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'unknown',
    component_hash TEXT,
    runner TEXT,
    pid INTEGER,
    container_id TEXT,
    container_name TEXT,
    started_at TEXT,
    last_hc_at TEXT,
    last_hc_ok INTEGER,
    unit_name TEXT,
    work_dir TEXT
)`,
		`CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id TEXT NOT NULL,
    component_hash TEXT,
    ts TEXT NOT NULL
)`,
	}
	for _, s := range stmts {
		if _, err := db.Exec(s); err != nil {
			db.Close()
			return nil, err
		}
	}
	// Best-effort migration: add container_name column if upgrading.
	if _, err := db.Exec(`ALTER TABLE components ADD COLUMN container_name TEXT`); err != nil {
		// ignore if column already exists
	}
	db.SetMaxOpenConns(1) // sqlite: serialize writes
	return &sqliteStore{db: db}, nil
}

func (s *sqliteStore) Close() error { return s.db.Close() }

func (s *sqliteStore) Get(ctx context.Context, id string) (*Component, error) {
	row := s.db.QueryRowContext(ctx,
		`SELECT id, status, COALESCE(component_hash,''), COALESCE(runner,''),
		         COALESCE(pid,0), COALESCE(container_id,''), COALESCE(container_name,''),
		         COALESCE(started_at,''), COALESCE(last_hc_at,''), COALESCE(last_hc_ok, 0),
		         COALESCE(unit_name,''), COALESCE(work_dir,'')
		 FROM components WHERE id=?`, id)
	var c Component
	var startedAt, lastHC string
	var lastOK int
	err := row.Scan(&c.ID, &c.Status, &c.ComponentHash, &c.Runner, &c.PID,
		&c.ContainerID, &c.ContainerName, &startedAt, &lastHC, &lastOK, &c.UnitName, &c.WorkDir)
	if err == sql.ErrNoRows {
		return nil, ErrNotFound
	}
	if err != nil {
		return nil, err
	}
	if startedAt != "" {
		t, _ := time.Parse(time.RFC3339, startedAt)
		c.StartedAt = &t
	}
	if lastHC != "" {
		t, _ := time.Parse(time.RFC3339, lastHC)
		c.LastHCAt = &t
	}
	c.LastHCOK = lastOK == 1
	return &c, nil
}

func (s *sqliteStore) Upsert(ctx context.Context, c *Component) error {
	var startedAt, lastHC string
	if c.StartedAt != nil {
		startedAt = c.StartedAt.UTC().Format(time.RFC3339)
	}
	if c.LastHCAt != nil {
		lastHC = c.LastHCAt.UTC().Format(time.RFC3339)
	}
	_, err := s.db.ExecContext(ctx, `
		INSERT INTO components(id,status,component_hash,runner,pid,container_id,container_name,started_at,last_hc_at,last_hc_ok,unit_name,work_dir)
		VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
		ON CONFLICT(id) DO UPDATE SET
		  status=excluded.status,
		  component_hash=excluded.component_hash,
		  runner=excluded.runner,
		  pid=excluded.pid,
		  container_id=excluded.container_id,
		  container_name=excluded.container_name,
		  started_at=excluded.started_at,
		  last_hc_at=excluded.last_hc_at,
		  last_hc_ok=excluded.last_hc_ok,
		  unit_name=excluded.unit_name,
		  work_dir=excluded.work_dir
	`,
		c.ID, c.Status, c.ComponentHash, c.Runner, c.PID, c.ContainerID, c.ContainerName,
		startedAt, lastHC, boolToInt(c.LastHCOK), c.UnitName, c.WorkDir)
	return err
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

func (s *sqliteStore) List(ctx context.Context) ([]*Component, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT id FROM components ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []string
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	out := make([]*Component, 0, len(ids))
	for _, id := range ids {
		c, err := s.Get(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

func (s *sqliteStore) Delete(ctx context.Context, id string) error {
	_, err := s.db.ExecContext(ctx, `DELETE FROM components WHERE id=?`, id)
	return err
}

func (s *sqliteStore) AppendHistory(ctx context.Context, componentID, hash string) error {
	_, err := s.db.ExecContext(ctx,
		`INSERT INTO history(component_id, component_hash, ts) VALUES (?, ?, ?)`,
		componentID, hash, time.Now().UTC().Format(time.RFC3339))
	return err
}

func (s *sqliteStore) History(ctx context.Context, componentID string, limit int) ([]HistoryEntry, error) {
	if limit <= 0 {
		limit = 10
	}
	rows, err := s.db.QueryContext(ctx,
		`SELECT id, component_id, component_hash, ts FROM history
		 WHERE component_id=? ORDER BY id DESC LIMIT ?`, componentID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []HistoryEntry
	for rows.Next() {
		var e HistoryEntry
		var ts string
		if err := rows.Scan(&e.ID, &e.ComponentID, &e.ComponentHash, &ts); err != nil {
			return nil, err
		}
		t, _ := time.Parse(time.RFC3339, ts)
		e.TS = t
		out = append(out, e)
	}
	return out, nil
}
