package redact_test


import (
	"encoding/json"
	"strings"
	"testing"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"

	"example.com/logredact/redact"
)

// --- helpers ---

func newInner() zapcore.Encoder {
	return zapcore.NewJSONEncoder(zapcore.EncoderConfig{
		MessageKey:     "msg",
		LevelKey:       "level",
		EncodeLevel:    zapcore.LowercaseLevelEncoder,
		EncodeTime:     zapcore.EpochTimeEncoder,
		EncodeDuration: zapcore.SecondsDurationEncoder,
	})
}

func encode(enc zapcore.Encoder, msg string, fields ...zapcore.Field) string {
	entry := zapcore.Entry{Level: zapcore.InfoLevel, Message: msg}
	buf, err := enc.EncodeEntry(entry, fields)
	if err != nil {
		panic(err)
	}
	return strings.TrimRight(buf.String(), "\n")
}

func parseJSON(t *testing.T, s string) map[string]interface{} {
	t.Helper()
	var m map[string]interface{}
	if err := json.Unmarshal([]byte(s), &m); err != nil {
		t.Fatalf("invalid JSON %q: %v", s, err)
	}
	return m
}

func nestedMap(t *testing.T, m map[string]interface{}, key string) map[string]interface{} {
	t.Helper()
	v, ok := m[key]
	if !ok {
		t.Fatalf("key %q not found in %v", key, m)
	}
	sub, ok := v.(map[string]interface{})
	if !ok {
		t.Fatalf("key %q is %T, want object: %v", key, v, v)
	}
	return sub
}

// --- test object marshalers ---

type testUser struct {
	Name     string
	Password string
	Age      int
	Email    string
}

func (u *testUser) MarshalLogObject(enc zapcore.ObjectEncoder) error {
	enc.AddString("name", u.Name)
	enc.AddString("password", u.Password)
	enc.AddInt("age", u.Age)
	enc.AddString("email", u.Email)
	return nil
}

type testRequest struct {
	Method  string
	Path    string
	Headers *testHeaders
}

func (r *testRequest) MarshalLogObject(enc zapcore.ObjectEncoder) error {
	enc.AddString("method", r.Method)
	enc.AddString("path", r.Path)
	return enc.AddObject("headers", r.Headers)
}

type testHeaders struct {
	ContentType   string
	Authorization string
	Secret        string
}

func (h *testHeaders) MarshalLogObject(enc zapcore.ObjectEncoder) error {
	enc.AddString("content_type", h.ContentType)
	enc.AddString("authorization", h.Authorization)
	enc.AddString("secret", h.Secret)
	return nil
}

type testItems []testItem

func (items testItems) MarshalLogArray(enc zapcore.ArrayEncoder) error {
	for i := range items {
		if err := enc.AppendObject(&items[i]); err != nil {
			return err
		}
	}
	return nil
}

type testItem struct {
	Name  string
	Token string
}

func (item *testItem) MarshalLogObject(enc zapcore.ObjectEncoder) error {
	enc.AddString("name", item.Name)
	enc.AddString("token", item.Token)
	return nil
}

// --- tests ---

func TestTopLevelMask(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "password", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)
	enc.AddString("username", "alice")
	enc.AddString("password", "s3cret!")

	out := encode(enc, "login")
	m := parseJSON(t, out)

	if m["username"] != "alice" {
		t.Errorf("username should be alice, got %v", m["username"])
	}
	if m["password"] != "[REDACTED]" {
		t.Errorf("password should be [REDACTED], got %v", m["password"])
	}
	if strings.Contains(out, "s3cret!") {
		t.Error("raw password found in output")
	}
}

func TestTopLevelDrop(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "internal_id", Action: redact.Drop},
		},
	}
	enc := redact.New(newInner(), cfg)
	enc.AddString("name", "alice")
	enc.AddString("internal_id", "xyz789")

	out := encode(enc, "lookup")
	m := parseJSON(t, out)

	if m["name"] != "alice" {
		t.Errorf("name should be alice, got %v", m["name"])
	}
	if _, ok := m["internal_id"]; ok {
		t.Error("internal_id should be dropped")
	}
}

func TestNestedObjectMask(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "user.password", Action: redact.Mask},
			{Pattern: "user.email", Action: redact.Drop},
		},
	}
	enc := redact.New(newInner(), cfg)

	user := &testUser{Name: "alice", Password: "s3cret", Age: 30, Email: "alice@co.com"}
	if err := enc.AddObject("user", user); err != nil {
		t.Fatal(err)
	}

	out := encode(enc, "profile")
	m := parseJSON(t, out)
	userMap := nestedMap(t, m, "user")

	if userMap["name"] != "alice" {
		t.Errorf("user.name should be alice, got %v", userMap["name"])
	}
	if userMap["password"] != "[REDACTED]" {
		t.Errorf("user.password should be [REDACTED], got %v", userMap["password"])
	}
	if _, ok := userMap["email"]; ok {
		t.Error("user.email should be dropped")
	}
	if strings.Contains(out, "s3cret") {
		t.Error("raw password found in output")
	}
	if strings.Contains(out, "alice@co.com") {
		t.Error("raw email found in output")
	}
}

func TestDeepNestedMask(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "request.headers.authorization", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)

	req := &testRequest{
		Method: "POST",
		Path:   "/api/v1/login",
		Headers: &testHeaders{
			ContentType:   "application/json",
			Authorization: "Bearer tok_abc123",
			Secret:        "visible",
		},
	}
	if err := enc.AddObject("request", req); err != nil {
		t.Fatal(err)
	}

	out := encode(enc, "api_call")
	m := parseJSON(t, out)
	reqMap := nestedMap(t, m, "request")
	hdrs := nestedMap(t, reqMap, "headers")

	if hdrs["content_type"] != "application/json" {
		t.Errorf("content_type wrong: %v", hdrs["content_type"])
	}
	if hdrs["authorization"] != "[REDACTED]" {
		t.Errorf("authorization should be [REDACTED], got %v", hdrs["authorization"])
	}
	if hdrs["secret"] != "visible" {
		t.Errorf("secret should be visible, got %v", hdrs["secret"])
	}
	if strings.Contains(out, "tok_abc123") {
		t.Error("raw authorization token found in output")
	}
}

func TestWildcardMatch(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "*.*.secret", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)

	req := &testRequest{
		Method: "GET",
		Path:   "/",
		Headers: &testHeaders{
			ContentType:   "text/plain",
			Authorization: "none",
			Secret:        "hidden_value",
		},
	}
	if err := enc.AddObject("request", req); err != nil {
		t.Fatal(err)
	}

	out := encode(enc, "test")

	if strings.Contains(out, "hidden_value") {
		t.Error("secret value should be redacted")
	}
	m := parseJSON(t, out)
	reqMap := nestedMap(t, m, "request")
	hdrs := nestedMap(t, reqMap, "headers")
	if hdrs["secret"] != "[REDACTED]" {
		t.Errorf("secret should be [REDACTED], got %v", hdrs["secret"])
	}
}

func TestClonePreservesRedaction(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "token", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)
	enc.AddString("ctx", "shared")

	clone := enc.Clone()

	cloneEnc, ok := clone.(*redact.Encoder)
	if !ok {
		t.Fatalf("Clone should return *redact.Encoder, got %T", clone)
	}

	// The clone should redact "token" when added as context
	cloneEnc.AddString("token", "clone_token")

	out := encode(cloneEnc, "from_clone")
	m := parseJSON(t, out)

	if m["token"] != "[REDACTED]" {
		t.Errorf("cloned encoder should redact token, got %v in: %s", m["token"], out)
	}
	if m["ctx"] != "shared" {
		t.Errorf("cloned encoder should have ctx, got: %s", out)
	}
	if strings.Contains(out, "clone_token") {
		t.Error("raw token found in cloned output")
	}

	// Original should not have clone's fields
	origOut := encode(enc, "from_orig")
	origM := parseJSON(t, origOut)
	if _, hasToken := origM["token"]; hasToken {
		t.Errorf("original should not have clone's token: %s", origOut)
	}
}

func TestEncodeEntryRedaction(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "password", Action: redact.Mask},
			{Pattern: "ssn", Action: redact.Drop},
		},
	}
	enc := redact.New(newInner(), cfg)

	fields := []zapcore.Field{
		zap.String("username", "alice"),
		zap.String("password", "pw123"),
		zap.String("ssn", "123-45-6789"),
	}
	out := encode(enc, "sensitive", fields...)
	m := parseJSON(t, out)

	if m["username"] != "alice" {
		t.Errorf("username should be alice: %s", out)
	}
	if m["password"] != "[REDACTED]" {
		t.Errorf("password should be [REDACTED]: %s", out)
	}
	if _, ok := m["ssn"]; ok {
		t.Errorf("ssn should be dropped: %s", out)
	}
	if strings.Contains(out, "pw123") {
		t.Error("raw password in output")
	}
	if strings.Contains(out, "123-45-6789") {
		t.Error("raw ssn in output")
	}
}

func TestEncodeEntryWithNestedObject(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "user.password", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)

	user := &testUser{Name: "bob", Password: "b0bpw", Age: 25, Email: "bob@test.com"}
	fields := []zapcore.Field{
		zap.Object("user", user),
	}
	out := encode(enc, "entry_obj", fields...)
	m := parseJSON(t, out)
	userMap := nestedMap(t, m, "user")

	if userMap["name"] != "bob" {
		t.Errorf("user.name wrong: %s", out)
	}
	if userMap["password"] != "[REDACTED]" {
		t.Errorf("user.password should be [REDACTED]: %s", out)
	}
	if strings.Contains(out, "b0bpw") {
		t.Error("raw password in output")
	}
}

func TestEncodeEntryIdempotent(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "secret", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)
	enc.AddString("ctx", "value")

	fields := []zapcore.Field{zap.String("secret", "hidden")}

	out1 := encode(enc, "first", fields...)
	out2 := encode(enc, "second", fields...)

	m1 := parseJSON(t, out1)
	m2 := parseJSON(t, out2)

	if m1["secret"] != "[REDACTED]" {
		t.Errorf("first call should mask secret: %s", out1)
	}
	if m2["secret"] != "[REDACTED]" {
		t.Errorf("second call should mask secret: %s", out2)
	}
	if m1["ctx"] != "value" {
		t.Errorf("ctx missing from first: %s", out1)
	}
	if m2["ctx"] != "value" {
		t.Errorf("ctx missing from second: %s", out2)
	}
	if m1["msg"] != "first" {
		t.Errorf("first message wrong: %s", out1)
	}
	if m2["msg"] != "second" {
		t.Errorf("second message wrong: %s", out2)
	}
}

func TestArrayObjectRedaction(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "items.token", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)

	items := testItems{
		{Name: "widget", Token: "tok_abc"},
		{Name: "gadget", Token: "tok_xyz"},
	}
	if err := enc.AddArray("items", items); err != nil {
		t.Fatal(err)
	}

	out := encode(enc, "array_test")

	if strings.Contains(out, "tok_abc") || strings.Contains(out, "tok_xyz") {
		t.Errorf("tokens should be redacted: %s", out)
	}
	if !strings.Contains(out, "widget") || !strings.Contains(out, "gadget") {
		t.Errorf("names should be present: %s", out)
	}

	// Parse and verify structure
	m := parseJSON(t, out)
	arr, ok := m["items"].([]interface{})
	if !ok {
		t.Fatalf("items should be array: %s", out)
	}
	if len(arr) != 2 {
		t.Fatalf("expected 2 items, got %d: %s", len(arr), out)
	}
	for i, elem := range arr {
		obj, ok := elem.(map[string]interface{})
		if !ok {
			t.Fatalf("item %d should be object: %v", i, elem)
		}
		if obj["token"] != "[REDACTED]" {
			t.Errorf("item %d token should be [REDACTED], got %v", i, obj["token"])
		}
	}
}

func TestNamespaceTracking(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "auth.token", Action: redact.Mask},
		},
	}
	enc := redact.New(newInner(), cfg)
	enc.OpenNamespace("auth")
	enc.AddString("user", "alice")
	enc.AddString("token", "tok_secret")

	out := encode(enc, "ns_test")
	m := parseJSON(t, out)
	authMap := nestedMap(t, m, "auth")

	if authMap["user"] != "alice" {
		t.Errorf("auth.user wrong: %s", out)
	}
	if authMap["token"] != "[REDACTED]" {
		t.Errorf("auth.token should be [REDACTED]: %s", out)
	}
	if strings.Contains(out, "tok_secret") {
		t.Error("raw token found in output")
	}
}

func TestMultipleRules(t *testing.T) {
	cfg := &redact.Config{
		Rules: []redact.Rule{
			{Pattern: "password", Action: redact.Mask},
			{Pattern: "*.password", Action: redact.Mask},
			{Pattern: "*.*.authorization", Action: redact.Mask},
			{Pattern: "user.email", Action: redact.Drop},
		},
	}
	enc := redact.New(newInner(), cfg)

	enc.AddString("password", "top_pw")
	enc.AddString("safe", "visible")

	user := &testUser{Name: "carol", Password: "carol_pw", Age: 28, Email: "carol@test.com"}
	if err := enc.AddObject("user", user); err != nil {
		t.Fatal(err)
	}

	req := &testRequest{
		Method: "PUT",
		Path:   "/update",
		Headers: &testHeaders{
			ContentType:   "application/json",
			Authorization: "Bearer xyz",
			Secret:        "not_matched",
		},
	}
	if err := enc.AddObject("request", req); err != nil {
		t.Fatal(err)
	}

	out := encode(enc, "multi")
	m := parseJSON(t, out)

	// top-level password masked
	if m["password"] != "[REDACTED]" {
		t.Errorf("top password should be masked: %s", out)
	}
	if m["safe"] != "visible" {
		t.Errorf("safe should be visible: %s", out)
	}

	// nested user
	userMap := nestedMap(t, m, "user")
	if userMap["password"] != "[REDACTED]" {
		t.Errorf("user.password should be masked: %s", out)
	}
	if _, ok := userMap["email"]; ok {
		t.Errorf("user.email should be dropped: %s", out)
	}

	// deep nested request
	reqMap := nestedMap(t, m, "request")
	hdrs := nestedMap(t, reqMap, "headers")
	if hdrs["authorization"] != "[REDACTED]" {
		t.Errorf("request.headers.authorization should be masked: %s", out)
	}
	// secret NOT matched by any rule ("request.headers.secret" doesn't match any pattern)
	if hdrs["secret"] != "not_matched" {
		t.Errorf("secret should be unmasked: %s", out)
	}

	// verify no sensitive values
	for _, sensitive := range []string{"top_pw", "carol_pw", "carol@test.com", "Bearer xyz"} {
		if strings.Contains(out, sensitive) {
			t.Errorf("sensitive value %q found in output: %s", sensitive, out)
		}
	}
}
