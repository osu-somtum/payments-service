-- osu-web store orders (PAYMENTS_BACKEND=osu-web): which order a payment was for.
ALTER TABLE donation_transactions
    ADD COLUMN store_order_id BIGINT UNSIGNED NULL AFTER target_user_id,
    ADD KEY store_order (store_order_id);
