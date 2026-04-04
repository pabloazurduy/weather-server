# frozen_string_literal: true

ROM::SQL.migration { change { set_column_type :model, :scale_factor, :float } }
