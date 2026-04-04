# frozen_string_literal: true

Hanami.app.configure_provider(:db) { Sequel.default_timezone = :utc }
