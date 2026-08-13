extends StudioTestCase
## The studio bridge's default address follows the page that served the game:
## /studio on the same origin at a domain root, /racing/studio when the game
## is served under a /racing path — the same export then answers at
## racing.ashaarena.com and at ashaarena.com/racing. Pure derivation table;
## the browser half only hands over origin + pathname.

const CASES: Array[Array] = [
	# The subdomain deploy, at the redirect page and under both export mounts.
	["https://racing.ashaarena.com/", "wss://racing.ashaarena.com/studio"],
	["https://racing.ashaarena.com", "wss://racing.ashaarena.com/studio"],
	["https://racing.ashaarena.com/webgpu/", "wss://racing.ashaarena.com/studio"],
	["https://racing.ashaarena.com/webgpu/index.html", "wss://racing.ashaarena.com/studio"],
	["https://racing.ashaarena.com/webgl/index.html", "wss://racing.ashaarena.com/studio"],
	# The apex-domain mount: everything under /racing rides the path prefix.
	["https://ashaarena.com/racing/", "wss://ashaarena.com/racing/studio"],
	["https://ashaarena.com/racing", "wss://ashaarena.com/racing/studio"],
	["https://ashaarena.com/racing/webgpu/index.html", "wss://ashaarena.com/racing/studio"],
	["https://ashaarena.com/racing/webgl/", "wss://ashaarena.com/racing/studio"],
	# …but the apex root itself is a domain root, and a merely similar path
	# segment ("/racing-club") is NOT the /racing mount — only exactly
	# "/racing[/…]" carries the prefix, everything else is the root rule.
	["https://ashaarena.com/", "wss://ashaarena.com/studio"],
	["https://ashaarena.com/racing-club/", "wss://ashaarena.com/studio"],
	# Deep links and local dev: query/hash never reach the prefix check, and
	# http dev origins downgrade to ws:// with the port kept.
	["https://racing.ashaarena.com/webgpu/index.html?ghost=g-7#x", "wss://racing.ashaarena.com/studio"],
	["http://localhost:8080/", "ws://localhost:8080/studio"],
	["http://127.0.0.1:8080/racing/", "ws://127.0.0.1:8080/racing/studio"],
]


func test_derivation_table() -> void:
	for pair in CASES:
		var page_url := str(pair[0])
		assert_eq(StudioClient.derive_ws_url(page_url), str(pair[1]),
			"derive_ws_url(%s)" % page_url)


func test_unparseable_pages_answer_empty() -> void:
	assert_eq(StudioClient.derive_ws_url(""), "", "no page, no derivation")
	assert_eq(StudioClient.derive_ws_url("   "), "")
	assert_eq(StudioClient.derive_ws_url("about:blank"), "", "not an http(s) page")
	assert_eq(StudioClient.derive_ws_url("https:///racing/"), "", "no host")
	assert_eq(StudioClient.derive_ws_url("ftp://racing.ashaarena.com/"), "",
		"only the page's own http(s) origin derives a socket")


## _configure keeps its priority order around the new derivation: an explicit
## base_url and the env override both still win, and offline stays parked.
func test_configure_priority_is_unchanged() -> void:
	var explicit := StudioClient.new()
	explicit.base_url = "ws://unit-test.invalid/studio"
	explicit._configure()
	assert_eq(explicit.base_url, "ws://unit-test.invalid/studio",
		"an explicitly set base_url always wins")
	explicit.free()

	# Headless there is no web origin to derive from, so the documented
	# default mount stands (when the suite's own env doesn't park the bridge).
	if not OS.has_environment("RACING_STUDIO_URL") \
			and OS.get_environment("RACING_SPECTATE_OFFLINE") != "1":
		var fallback := StudioClient.new()
		fallback._configure()
		assert_eq(fallback.base_url, StudioClient.DEFAULT_BASE_URL,
			"off the web the default mount stands")
		fallback.free()
