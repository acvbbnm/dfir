-- EA WordPress 정상 데이터 시드
-- WordPress 설치 완료 후 실행한다.
-- 20 users, 50 posts, 20 media (미디어 파일은 S3 배치로 별도 업로드)

-- 사용자 20명 (비밀번호는 배포 시 wp-cli로 설정)
-- wp user create user01 user01@lab.local --role=subscriber
-- wp user create user02 user02@lab.local --role=subscriber
-- ... (반복)
-- wp user create editor01 editor01@lab.local --role=editor
-- wp user create editor02 editor02@lab.local --role=editor
-- wp user create author01 author01@lab.local --role=author

-- 아래는 wp-cli batch 스크립트로 실행:

-- seed_users.sh:
-- #!/bin/bash
-- for i in $(seq -w 1 15); do
--   wp user create "user${i}" "user${i}@lab.local" --role=subscriber --user_pass="LabUser${i}!" --path=/var/www/wordpress
-- done
-- for i in $(seq -w 1 3); do
--   wp user create "editor${i}" "editor${i}@lab.local" --role=editor --user_pass="LabEditor${i}!" --path=/var/www/wordpress
-- done
-- wp user create "author01" "author01@lab.local" --role=author --user_pass="LabAuthor01!" --path=/var/www/wordpress
-- wp user create "author02" "author02@lab.local" --role=author --user_pass="LabAuthor02!" --path=/var/www/wordpress

-- 카테고리
INSERT INTO wp_terms (name, slug) VALUES
  ('공지사항', 'notice'),
  ('기술블로그', 'tech-blog'),
  ('회사소식', 'company-news'),
  ('채용', 'careers'),
  ('자료실', 'resources');

-- 글 50개 (wp-cli batch):
-- seed_posts.sh:
-- #!/bin/bash
-- CATEGORIES=("notice" "tech-blog" "company-news" "careers" "resources")
-- AUTHORS=(1 2 3 4 5)  # admin + 4 editors/authors
-- for i in $(seq 1 50); do
--   CAT=${CATEGORIES[$((RANDOM % 5))]}
--   AUTHOR=${AUTHORS[$((RANDOM % 5))]}
--   wp post create --post_title="테스트 게시글 ${i}" \
--     --post_content="이것은 정상 서비스 시드 데이터의 ${i}번째 게시글입니다. 다양한 카테고리와 작성자로 기준선 트래픽을 생성합니다." \
--     --post_status=publish \
--     --post_author="${AUTHOR}" \
--     --post_category="${CAT}" \
--     --path=/var/www/wordpress
-- done

-- 미디어 20개 (wp-cli batch):
-- seed_media.sh:
-- #!/bin/bash
-- for i in $(seq -w 1 20); do
--   # 1x1 PNG placeholder 생성
--   convert -size 640x480 xc:gray "media_${i}.png"
--   wp media import "media_${i}.png" --title="테스트 이미지 ${i}" --path=/var/www/wordpress
--   rm "media_${i}.png"
-- done

-- DVWA 전용 DB 사용자 (RDS에서 실행)
CREATE DATABASE IF NOT EXISTS dvwa CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'dvwa_user'@'%' IDENTIFIED BY 'DVWA_PASSWORD_CHANGE_ME';
GRANT ALL PRIVILEGES ON dvwa.* TO 'dvwa_user'@'%';

-- 읽기 전용 사용자 (모니터링/감사용)
CREATE USER IF NOT EXISTS 'readonly_user'@'%' IDENTIFIED BY 'READONLY_PASSWORD_CHANGE_ME';
GRANT SELECT ON wordpress.* TO 'readonly_user'@'%';

FLUSH PRIVILEGES;
