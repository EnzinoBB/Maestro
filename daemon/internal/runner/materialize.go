package runner

import (
	"archive/tar"
	"bytes"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"time"
)

const defaultRetainReleases = 5

// MaterializeArchive extracts a ConfigArchive onto the host filesystem
// according to its Strategy. For atomic_symlink it writes to
// <Dest>/releases/<ContentHash>/, flips <Dest>/current → releases/<hash>,
// and GCs older releases to defaultRetainReleases entries.
func MaterializeArchive(arc ConfigArchive) error {
	if arc.Dest == "" {
		return errors.New("archive Dest is required")
	}
	tarBytes, err := base64.StdEncoding.DecodeString(arc.TarB64)
	if err != nil {
		return fmt.Errorf("decode tar_b64: %w", err)
	}

	switch arc.Strategy {
	case "overwrite":
		return extractTar(tarBytes, arc.Dest, os.FileMode(effectiveMode(arc.Mode)))
	case "atomic":
		tmp := arc.Dest + ".tmp"
		_ = os.RemoveAll(tmp)
		if err := extractTar(tarBytes, tmp, os.FileMode(effectiveMode(arc.Mode))); err != nil {
			return err
		}
		_ = os.RemoveAll(arc.Dest)
		return os.Rename(tmp, arc.Dest)
	case "atomic_symlink", "":
		return materializeAtomicSymlink(arc.Dest, arc.ContentHash, tarBytes, os.FileMode(effectiveMode(arc.Mode)))
	default:
		return fmt.Errorf("unsupported strategy: %s", arc.Strategy)
	}
}

func effectiveMode(m int) int {
	if m == 0 {
		return 0o755
	}
	return m
}

func materializeAtomicSymlink(dest, hash string, tarBytes []byte, mode os.FileMode) error {
	if hash == "" {
		return errors.New("atomic_symlink requires ContentHash")
	}
	releasesDir := filepath.Join(dest, "releases")
	if err := os.MkdirAll(releasesDir, mode); err != nil {
		return fmt.Errorf("mkdir releases: %w", err)
	}
	releasePath := filepath.Join(releasesDir, hash)
	currentLink := filepath.Join(dest, "current")

	// Idempotency: if release already exists AND current points to it, no-op.
	if fi, err := os.Stat(releasePath); err == nil && fi.IsDir() {
		if target, lerr := os.Readlink(currentLink); lerr == nil && filepath.Base(target) == hash {
			return nil
		}
	} else {
		// extract fresh
		if err := extractTar(tarBytes, releasePath, mode); err != nil {
			return err
		}
	}

	// Atomic flip: symlink write to <dest>/current.tmp then rename.
	// On Linux/macOS, os.Symlink + os.Rename is atomic w.r.t. readers.
	tmpLink := filepath.Join(dest, "current.tmp")
	_ = os.Remove(tmpLink)
	relTarget := filepath.Join("releases", hash)
	if err := os.Symlink(relTarget, tmpLink); err != nil {
		return fmt.Errorf("symlink tmp: %w", err)
	}
	if err := os.Rename(tmpLink, currentLink); err != nil {
		return fmt.Errorf("rename current: %w", err)
	}

	return gcOldReleases(releasesDir, defaultRetainReleases)
}

func extractTar(tarBytes []byte, dest string, mode os.FileMode) error {
	if err := os.MkdirAll(dest, mode); err != nil {
		return fmt.Errorf("mkdir dest: %w", err)
	}
	tr := tar.NewReader(bytes.NewReader(tarBytes))
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("tar next: %w", err)
		}
		// security: reject absolute or .. paths
		cleaned := filepath.Clean(hdr.Name)
		if filepath.IsAbs(cleaned) || cleaned == ".." || len(cleaned) >= 2 && cleaned[:2] == ".." {
			return fmt.Errorf("unsafe tar entry: %s", hdr.Name)
		}
		target := filepath.Join(dest, cleaned)
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, os.FileMode(hdr.Mode)); err != nil {
				return err
			}
		case tar.TypeReg, tar.TypeRegA:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode))
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				_ = f.Close()
				return err
			}
			_ = f.Close()
		default:
			// skip symlinks and other types for safety in Phase 1
		}
	}
	return nil
}

func gcOldReleases(releasesDir string, retain int) error {
	entries, err := os.ReadDir(releasesDir)
	if err != nil {
		return nil // nothing to GC
	}
	type entInfo struct {
		name  string
		mtime time.Time
	}
	var infos []entInfo
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		fi, err := os.Stat(filepath.Join(releasesDir, e.Name()))
		if err != nil {
			continue
		}
		infos = append(infos, entInfo{name: e.Name(), mtime: fi.ModTime()})
	}
	if len(infos) <= retain {
		return nil
	}
	sort.Slice(infos, func(i, j int) bool { return infos[i].mtime.Before(infos[j].mtime) })
	toRemove := len(infos) - retain
	for _, inf := range infos[:toRemove] {
		_ = os.RemoveAll(filepath.Join(releasesDir, inf.name))
	}
	return nil
}

// WriteConfigFiles materializes simple base64-encoded single files to disk.
// Used for config.templates rendered by the CP. Each file is written with
// os.WriteFile (non-atomic); for atomic semantics use MaterializeArchive.
func WriteConfigFiles(baseDir string, files []ConfigFile) error {
	for _, f := range files {
		dest := f.Dest
		if dest == "" {
			continue
		}
		if !filepath.IsAbs(dest) {
			dest = filepath.Join(baseDir, dest)
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			return fmt.Errorf("mkdir %s: %w", filepath.Dir(dest), err)
		}
		data, err := base64.StdEncoding.DecodeString(f.ContentB64)
		if err != nil {
			return fmt.Errorf("decode %s: %w", dest, err)
		}
		mode := os.FileMode(f.Mode)
		if mode == 0 {
			mode = 0o640
		}
		if err := os.WriteFile(dest, data, mode); err != nil {
			return fmt.Errorf("write %s: %w", dest, err)
		}
	}
	return nil
}
