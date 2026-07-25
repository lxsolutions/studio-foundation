class_name FrontGate
extends RefCounted

## Which door the web export opens on. Any sign of a rider, a Plaza handoff
## token waiting in the URL (or env), or a remembered owner code, walks them
## straight to the rider's gate; strangers get the stands and a door in.

const DEST_RIDER := "rider"
const DEST_STANDS := "stands"


static func boot_destination(token_waiting: bool, code_remembered: bool) -> String:
	if token_waiting or code_remembered:
		return DEST_RIDER
	return DEST_STANDS
