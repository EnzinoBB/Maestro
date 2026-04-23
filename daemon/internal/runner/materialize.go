package runner

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
)

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
