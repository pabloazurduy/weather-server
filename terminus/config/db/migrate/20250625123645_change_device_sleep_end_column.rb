# frozen_string_literal: true

ROM::SQL.migration { change { rename_column :devices, :sleep_end_at, :sleep_stop_at } }
