// Experimental entrypoint support, copied into each pinned upstream source tree.
package main

import (
	"context"
	"errors"
	"fmt"
	"os"
	"strings"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

// runTraced enables the upstream instrumentation without changing build logic.
// The first experiment deliberately starts an independent trace for each CLI.
func runTraced(ctx context.Context, service string, run func(context.Context) error) (err error) {
	if os.Getenv("OTEL_TRACES_EXPORTER") != "otlp" {
		return run(ctx)
	}
	for _, arg := range os.Args[1:] {
		if arg == "--trace" || strings.HasPrefix(arg, "--trace=") {
			return errors.New("this experiment cannot combine OTLP with melange --trace (it replaces the global provider)")
		}
	}

	exporter, err := otlptracegrpc.New(ctx)
	if err != nil {
		return fmt.Errorf("initialize OTLP exporter: %w", err)
	}
	res, err := resource.New(ctx,
		resource.WithAttributes(attribute.String("service.name", service)),
		resource.WithFromEnv(), resource.WithTelemetrySDK(),
	)
	if err != nil {
		_ = exporter.Shutdown(context.Background())
		return fmt.Errorf("initialize trace resource: %w", err)
	}
	tp := sdktrace.NewTracerProvider(
		sdktrace.WithResource(res),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
		sdktrace.WithBatcher(exporter, sdktrace.WithMaxQueueSize(8192)),
	)
	otel.SetTracerProvider(tp)
	name := service
	if len(os.Args) > 1 {
		name += " " + os.Args[1]
	}
	ctx, span := tp.Tracer("chainguard-build-traces/experiment").Start(ctx, name)
	fmt.Fprintf(os.Stderr, "TRACE service=%s trace_id=%s\n", service, span.SpanContext().TraceID())
	defer func() {
		if err != nil {
			span.RecordError(err)
			span.SetStatus(codes.Error, err.Error())
		}
		span.End()
		// A failed/interrupted command must also drain the batch processor.
		flushCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		if flushErr := tp.Shutdown(flushCtx); flushErr != nil {
			err = errors.Join(err, fmt.Errorf("flush traces: %w", flushErr))
		}
	}()
	return run(ctx)
}
