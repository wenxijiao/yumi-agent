package main

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
)

// Thin entry so you can run `go run .` without a separate app main.
// Remove this file when you integrate InitKumi() into your own program.
func main() {
	InitKumi()
	fmt.Println("Kumi edge running. Press Ctrl+C to stop.")
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	<-sigCh
}
