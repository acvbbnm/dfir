<?php
// Execute once by an operator after scoped DB users are provisioned. No credentials in stdout.
if (PHP_SAPI !== 'cli') { http_response_code(403); exit; }
define('WP_INSTALLING', true);
require '/var/www/wordpress/wp-load.php';
require_once ABSPATH.'wp-admin/includes/upgrade.php';
if (!is_blog_installed()) {
    $password=bin2hex(random_bytes(24));
    if (!is_dir('/root/ea-credentials')) { mkdir('/root/ea-credentials',0700,true); }
    $old=umask(0077);
    file_put_contents('/root/ea-credentials/wp-admin.json',json_encode(['username'=>'ea-admin','password'=>$password]));
    umask($old);
    wp_install('EA Company Portal','ea-admin','ea-admin@example.invalid',false,'',$password);
}
for ($i=1;$i<=20;$i++) {
    $login='ea-user-'.$i;
    if (!username_exists($login)) {
        $id=wp_create_user($login,bin2hex(random_bytes(24)),$login.'@example.invalid');
        if (is_wp_error($id)) { throw new RuntimeException($id->get_error_message()); }
        (new WP_User($id))->set_role('subscriber');
    }
}
for ($i=1;$i<=50;$i++) {
    $slug='ea-training-post-'.$i;
    if (!get_page_by_path($slug,OBJECT,'post')) {
        $id=wp_insert_post(['post_name'=>$slug,'post_title'=>'Company update '.$i,
            'post_content'=>'Synthetic training content. No real customer data.',
            'post_status'=>'publish','post_author'=>1],true);
        if (is_wp_error($id)) { throw new RuntimeException($id->get_error_message()); }
    }
}
foreach (glob('/var/log/wp-audit/*.json') as $file) { chown($file,'www-data'); chgrp($file,'www-data'); chmod($file,0640); }
echo "WordPress installed; 20 synthetic users and 50 posts present.\n";
