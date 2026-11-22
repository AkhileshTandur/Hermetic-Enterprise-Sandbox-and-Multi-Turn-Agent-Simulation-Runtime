// A bounded Go client for the Python evaluation API. Measures completed runs, not submissions.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"sync/atomic"
	"time"
)

func main() {
	base := flag.String("url", "http://localhost:8000", "sandbox API")
	spec := flag.String("spec", "examples/ticket.json", "scenario JSON")
	n := flag.Int("n", 20, "episodes")
	workers := flag.Int("workers", 4, "concurrent clients")
	flag.Parse()
	if *n < 1 || *workers < 1 {
		panic("n and workers must be positive")
	}
	body, err := os.ReadFile(*spec)
	if err != nil {
		panic(err)
	}
	if !json.Valid(body) {
		panic("invalid JSON spec")
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	client := &http.Client{Timeout: 15 * time.Second}
	jobs := make(chan int)
	var wg sync.WaitGroup
	var passed, failed atomic.Int64
	start := time.Now()
	for i := 0; i < *workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for range jobs {
				if run(ctx, client, *base, body) == nil {
					passed.Add(1)
				} else {
					failed.Add(1)
				}
			}
		}()
	}
	for i := 0; i < *n; i++ {
		select {
		case jobs <- i:
		case <-ctx.Done():
			close(jobs)
			wg.Wait()
			return
		}
	}
	close(jobs)
	wg.Wait()
	json.NewEncoder(os.Stdout).Encode(map[string]any{"episodes": *n, "workers": *workers, "passed": passed.Load(), "failed": failed.Load(), "elapsed_seconds": time.Since(start).Seconds()})
	if failed.Load() > 0 {
		os.Exit(1)
	}
}
func run(parent context.Context, c *http.Client, base string, body []byte) error {
	ctx, cancel := context.WithTimeout(parent, 2*time.Minute)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST", base+"/runs", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 202 {
		return fmt.Errorf("submit: %d", resp.StatusCode)
	}
	var result struct {
		RunID string `json:"run_id"`
	}
	if err = json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return err
	}
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			req, _ = http.NewRequestWithContext(ctx, "GET", base+"/runs/"+result.RunID, nil)
			r, e := c.Do(req)
			if e != nil {
				return e
			}
			var status struct {
				Status string `json:"status"`
			}
			e = json.NewDecoder(r.Body).Decode(&status)
			r.Body.Close()
			if e != nil {
				return e
			}
			switch status.Status {
			case "passed":
				return nil
			case "queued", "running":
				continue
			default:
				return fmt.Errorf("run: %s", status.Status)
			}
		}
	}
}
