class_name StudioLocalization
extends RefCounted
## Localization foundation: locale selection + translation lookup. Games ship
## Godot Translation resources (imported CSV/PO under res://i18n/); this wraps
## TranslationServer so shared UI never calls it directly.

var current_locale: String = "en"


func initialize(default_locale: String) -> void:
	set_locale(default_locale)


func set_locale(locale: String) -> void:
	current_locale = locale
	TranslationServer.set_locale(locale)


func available_locales() -> PackedStringArray:
	return TranslationServer.get_loaded_locales()


## Translate with graceful fallback to the key itself.
func t(key: StringName) -> String:
	var translated: StringName = TranslationServer.translate(key)
	return str(translated)
