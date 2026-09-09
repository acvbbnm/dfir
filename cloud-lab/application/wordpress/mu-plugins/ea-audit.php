<?php
/**
 * EA WordPress Audit Logger
 * 로그인, 글, 업로드, 권한 변경을 JSON으로 /var/log/wp-audit/에 기록한다.
 */

defined('ABSPATH') || exit;

class EA_Audit_Logger {
    private $log_dir = '/var/log/wp-audit';

    public function __construct() {
        add_action('wp_login', [$this, 'on_login'], 10, 2);
        add_action('wp_login_failed', [$this, 'on_login_failed']);
        add_action('wp_logout', [$this, 'on_logout']);
        add_action('save_post', [$this, 'on_save_post'], 10, 3);
        add_action('delete_post', [$this, 'on_delete_post']);
        add_action('add_attachment', [$this, 'on_upload']);
        add_action('set_user_role', [$this, 'on_role_change'], 10, 3);
        add_action('profile_update', [$this, 'on_profile_update'], 10, 2);
    }

    private function write_log(string $action, array $data): void {
        $entry = [
            'timestamp' => gmdate('Y-m-d\TH:i:s.v\Z'),
            'action'    => $action,
            'client_ip' => $_SERVER['REMOTE_ADDR'] ?? 'unknown',
            'user_agent'=> $_SERVER['HTTP_USER_AGENT'] ?? '',
        ];
        $entry = array_merge($entry, $data);

        $filename = $this->log_dir . '/audit-' . gmdate('Y-m-d') . '.json';
        $line = json_encode($entry, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n";

        @file_put_contents($filename, $line, FILE_APPEND | LOCK_EX);
    }

    public function on_login(string $user_login, \WP_User $user): void {
        $this->write_log('login_success', [
            'user_id'    => $user->ID,
            'user_login' => $user_login,
            'roles'      => $user->roles,
        ]);
    }

    public function on_login_failed(string $username): void {
        $this->write_log('login_failed', [
            'attempted_user' => $username,
        ]);
    }

    public function on_logout(): void {
        $user = wp_get_current_user();
        $this->write_log('logout', [
            'user_id'    => $user->ID,
            'user_login' => $user->user_login,
        ]);
    }

    public function on_save_post(int $post_id, \WP_Post $post, bool $update): void {
        if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) {
            return;
        }
        $this->write_log($update ? 'post_updated' : 'post_created', [
            'user_id'    => get_current_user_id(),
            'post_id'    => $post_id,
            'post_type'  => $post->post_type,
            'post_status'=> $post->post_status,
            'post_title' => mb_substr($post->post_title, 0, 100),
        ]);
    }

    public function on_delete_post(int $post_id): void {
        $this->write_log('post_deleted', [
            'user_id' => get_current_user_id(),
            'post_id' => $post_id,
        ]);
    }

    public function on_upload(int $attachment_id): void {
        $file = get_attached_file($attachment_id);
        $this->write_log('file_uploaded', [
            'user_id'       => get_current_user_id(),
            'attachment_id' => $attachment_id,
            'filename'      => basename($file),
            'size_bytes'    => filesize($file) ?: 0,
            'mime_type'     => get_post_mime_type($attachment_id),
        ]);
    }

    public function on_role_change(int $user_id, string $new_role, array $old_roles): void {
        $this->write_log('role_changed', [
            'changed_by' => get_current_user_id(),
            'target_user'=> $user_id,
            'old_roles'  => $old_roles,
            'new_role'   => $new_role,
        ]);
    }

    public function on_profile_update(int $user_id, \WP_User $old_user_data): void {
        $this->write_log('profile_updated', [
            'changed_by' => get_current_user_id(),
            'target_user'=> $user_id,
        ]);
    }
}

new EA_Audit_Logger();
