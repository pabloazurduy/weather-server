# frozen_string_literal: true

module Terminus
  module Relations
    # The palette relation.
    class Palette < DB::Relation
      schema :palette, infer: true
    end
  end
end
