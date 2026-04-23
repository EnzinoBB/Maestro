package runner

import (
	"archive/tar"
	"bytes"
	"encoding/base64"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func tarOf(files map[string]string) string {
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	for name, content := range files {
		_ = tw.WriteHeader(&tar.Header{Name: name, Mode: 0644, Size: int64(len(content))})
		_, _ = tw.Write([]byte(content))
	}
	_ = tw.Close()
	return base64.StdEncoding.EncodeToString(buf.Bytes())
}

// symlinkUnavailable returns true when os.Symlink is not permitted on this OS/user.
// On Windows without Developer Mode or admin rights, the error is localised
// (e.g. Italian "privilegio") but always contains "symlink" from our wrapper prefix.
func symlinkUnavailable(err error) bool {
	if err == nil || runtime.GOOS != "windows" {
		return false
	}
	msg := err.Error()
	return strings.Contains(msg, "symlink") || strings.Contains(msg, "privilege") || strings.Contains(msg, "privilegio")
}

func TestMaterializeArchiveOverwrite(t *testing.T) {
	dir := t.TempDir()
	arc := ConfigArchive{
		Dest: filepath.Join(dir, "site"), Strategy: "overwrite", Mode: 0o755,
		TarB64:      tarOf(map[string]string{"index.html": "<h1>hi</h1>"}),
		ContentHash: "deadbeef",
	}
	if err := MaterializeArchive(arc); err != nil {
		t.Fatalf("MaterializeArchive: %v", err)
	}
	b, err := os.ReadFile(filepath.Join(dir, "site", "index.html"))
	if err != nil || string(b) != "<h1>hi</h1>" {
		t.Fatalf("content mismatch: %v %q", err, string(b))
	}
}

func TestMaterializeArchiveAtomicSymlink(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "site")
	// first deploy
	arc1 := ConfigArchive{
		Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
		TarB64:      tarOf(map[string]string{"index.html": "v1"}),
		ContentHash: "aaa",
	}
	if err := MaterializeArchive(arc1); err != nil {
		if symlinkUnavailable(err) {
			t.Skip("symlink requires admin/dev-mode on Windows")
		}
		t.Fatal(err)
	}
	// current symlink must point to releases/aaa
	target, err := os.Readlink(filepath.Join(dest, "current"))
	if err != nil {
		t.Fatalf("readlink: %v", err)
	}
	if filepath.Base(target) != "aaa" {
		t.Fatalf("expected current -> releases/aaa, got %s", target)
	}
	// content via symlink
	b, _ := os.ReadFile(filepath.Join(dest, "current", "index.html"))
	if string(b) != "v1" {
		t.Fatalf("v1 content mismatch: %q", string(b))
	}
	// second deploy, different hash
	arc2 := ConfigArchive{
		Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
		TarB64:      tarOf(map[string]string{"index.html": "v2"}),
		ContentHash: "bbb",
	}
	if err := MaterializeArchive(arc2); err != nil {
		t.Fatal(err)
	}
	target, _ = os.Readlink(filepath.Join(dest, "current"))
	if filepath.Base(target) != "bbb" {
		t.Fatalf("expected current -> releases/bbb, got %s", target)
	}
	b, _ = os.ReadFile(filepath.Join(dest, "current", "index.html"))
	if string(b) != "v2" {
		t.Fatalf("v2 content mismatch")
	}
	// releases/aaa still exists (for rollback)
	if _, err := os.Stat(filepath.Join(dest, "releases", "aaa")); err != nil {
		t.Fatalf("releases/aaa should still exist: %v", err)
	}
}

func TestMaterializeArchiveIdempotent(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "site")
	arc := ConfigArchive{
		Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
		TarB64:      tarOf(map[string]string{"x": "y"}),
		ContentHash: "samehash",
	}
	if err := MaterializeArchive(arc); err != nil {
		if symlinkUnavailable(err) {
			t.Skip("symlink requires admin/dev-mode on Windows")
		}
		t.Fatal(err)
	}
	// second call with same hash: should be a no-op (not re-extract)
	if err := MaterializeArchive(arc); err != nil {
		t.Fatal(err)
	}
	// current symlink still points to samehash
	target, _ := os.Readlink(filepath.Join(dest, "current"))
	if filepath.Base(target) != "samehash" {
		t.Fatalf("idempotent failed: %s", target)
	}
}

func TestMaterializeArchiveRetainsMaxFive(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "site")
	for i, h := range []string{"h1", "h2", "h3", "h4", "h5", "h6", "h7"} {
		arc := ConfigArchive{
			Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
			TarB64:      tarOf(map[string]string{"v": string(rune('a' + i))}),
			ContentHash: h,
		}
		if err := MaterializeArchive(arc); err != nil {
			if symlinkUnavailable(err) {
				t.Skip("symlink requires admin/dev-mode on Windows")
			}
			t.Fatalf("deploy %s: %v", h, err)
		}
	}
	entries, _ := os.ReadDir(filepath.Join(dest, "releases"))
	if len(entries) != 5 {
		t.Fatalf("expected 5 releases retained, got %d: %v", len(entries), entries)
	}
	// oldest two (h1, h2) should be gone
	for _, old := range []string{"h1", "h2"} {
		if _, err := os.Stat(filepath.Join(dest, "releases", old)); err == nil {
			t.Fatalf("expected %s to be GC'd", old)
		}
	}
}
