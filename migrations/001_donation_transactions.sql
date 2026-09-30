-- donation_transactions: every TrueMoney, PromptPay and Stripe donation and its review.
-- bancho.py already has this table in its database; with PAYMENTS_BACKEND=osu-web, create it in
-- this service's own database (DB_NAME).
CREATE TABLE IF NOT EXISTS donation_transactions (
    id                   INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    provider             ENUM('truemoney', 'promptpay', 'stripe') NOT NULL,
    status               ENUM('pending', 'success', 'failed') NOT NULL DEFAULT 'pending',
    donor_user_id        INT UNSIGNED NOT NULL,
    target_user_id       INT UNSIGNED NOT NULL,
    requested_amount_thb DECIMAL(10, 2) NOT NULL DEFAULT 0,
    approved_amount_thb  DECIMAL(10, 2) NULL,
    days_requested       DECIMAL(10, 2) NOT NULL DEFAULT 0,
    days_granted         DECIMAL(10, 2) NULL,
    -- When the donator/supporter time ends after this donation (unix time).
    donor_end            BIGINT NULL,
    anonymous            TINYINT(1) NOT NULL DEFAULT 0,
    message              VARCHAR(280) NULL,
    -- Stripe checkout session id, or a hash of the TrueMoney voucher.
    provider_reference   VARCHAR(255) NULL,
    slip_path            VARCHAR(255) NULL,
    slip_token           VARCHAR(64) NULL,
    reviewed_by          INT UNSIGNED NULL,
    reviewed_at          DATETIME NULL,
    review_note          VARCHAR(500) NULL,
    decision_source      VARCHAR(32) NULL,
    created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    KEY provider_reference (provider, provider_reference),
    UNIQUE KEY slip_token (slip_token),
    KEY status (status, id),
    KEY donor (donor_user_id),
    KEY target (target_user_id)
) DEFAULT CHARSET = utf8mb4;
