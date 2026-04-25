package metrics

import "testing"

func TestItoaSec(t *testing.T) {
	cases := []struct {
		in  int
		out string
	}{
		{0, "0s"},
		{1, "1s"},
		{15, "15s"},
		{30, "30s"},
		{120, "120s"},
	}
	for _, c := range cases {
		got := itoaSec(c.in)
		if got != c.out {
			t.Errorf("itoaSec(%d) = %q, want %q", c.in, got, c.out)
		}
	}
}
