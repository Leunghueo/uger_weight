package main

import (
	"context"
	"errors"
	"log"
	"math/rand"
	"net"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

const (
	listenAddr        = "172.31.208.1:10000"
	maxConcurrentConn = 20
	randomMinValue    = 0x1100
	randomMaxValue    = 0xAABB
)

func main() {
	logger := log.New(os.Stdout, "vsp_sim ", log.LstdFlags|log.Lmicroseconds)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	server := &Server{
		logger: logger,
		rng:    rand.New(rand.NewSource(time.Now().UnixNano())),
		slots:  make(chan struct{}, maxConcurrentConn),
	}

	if err := server.run(ctx); err != nil && !errors.Is(err, context.Canceled) {
		logger.Fatalf("server stopped with error: %v", err)
	}
}

type Server struct {
	logger *log.Logger
	rng    *rand.Rand
	mu     sync.Mutex
	slots  chan struct{}
}

func (s *Server) run(ctx context.Context) error {
	listener, err := net.Listen("tcp", listenAddr)
	if err != nil {
		return err
	}
	defer listener.Close()

	s.logger.Printf("listen addr=%s max_conn=%d resp=01 04 04 00 00 XX XX 00 00 range=[%04X,%04X]", listenAddr, cap(s.slots), randomMinValue, randomMaxValue)

	go func() {
		<-ctx.Done()
		_ = listener.Close()
	}()

	var wg sync.WaitGroup
	defer wg.Wait()

	for {
		conn, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return ctx.Err()
			}
			if errors.Is(err, net.ErrClosed) {
				return ctx.Err()
			}
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Temporary() {
				time.Sleep(50 * time.Millisecond)
				continue
			}
			return err
		}

		s.slots <- struct{}{}
		wg.Add(1)
		go func(c net.Conn) {
			defer wg.Done()
			defer func() { <-s.slots }()
			s.handleConn(c)
		}(conn)
	}
}

func (s *Server) handleConn(conn net.Conn) {
	defer conn.Close()

	buffer := make([]byte, 1024)
	for {
		_ = conn.SetDeadline(time.Now().Add(2 * time.Second))
		n, err := conn.Read(buffer)
		if n > 0 {
			if _, writeErr := conn.Write(s.buildResponse()); writeErr != nil {
				s.logger.Printf("write response remote=%s err=%v", conn.RemoteAddr(), writeErr)
				return
			}
		}
		if err != nil {
			if errors.Is(err, os.ErrDeadlineExceeded) {
				continue
			}
			return
		}
	}
}

func (s *Server) buildResponse() []byte {
	value := s.randomValue()
	return []byte{
		0x01, 0x04, 0x04,
		0x00, 0x00,
		byte(value >> 8), byte(value),
		0x00, 0x00,
	}
}

func (s *Server) randomValue() uint16 {
	s.mu.Lock()
	defer s.mu.Unlock()
	return uint16(s.rng.Intn(randomMaxValue-randomMinValue+1) + randomMinValue)
}
