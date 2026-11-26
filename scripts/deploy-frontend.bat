@echo off
setlocal
rem Build the Angular app and publish it to the S3 bucket behind CloudFront.
rem Requires the stacks to be deployed first: cd infra ^&^& cdk deploy --all --profile PROFILE
rem
rem Usage:
rem   deploy-frontend.bat PROFILE [REGION]      (REGION defaults to eu-west-3)

set "PROFILE=%~1"
set "REGION=%~2"
if "%PROFILE%"=="" (
  echo Usage: deploy-frontend.bat PROFILE [REGION]
  exit /b 1
)
if "%REGION%"=="" set "REGION=eu-west-3"
set "OPTS=--profile %PROFILE% --region %REGION%"
set "FRONTEND=%~dp0..\frontend"
set "OUT=%FRONTEND%\dist\nightmare-resolver\browser"

echo Reading stack outputs...
for /f "delims=" %%V in ('aws cloudformation describe-stacks --stack-name NightmareResolverWeb --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text %OPTS%') do set "BUCKET=%%V"
for /f "delims=" %%V in ('aws cloudformation describe-stacks --stack-name NightmareResolverWeb --query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text %OPTS%') do set "DIST=%%V"
for /f "delims=" %%V in ('aws cloudformation describe-stacks --stack-name NightmareResolverWeb --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue" --output text %OPTS%') do set "SITE=%%V"
for /f "delims=" %%V in ('aws cloudformation describe-stacks --stack-name NightmareResolver --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text %OPTS%') do set "API=%%V"
if not defined BUCKET ( echo Stack NightmareResolverWeb not found. Deploy it first. & exit /b 1 )
if not defined API ( echo Stack NightmareResolver not found. Deploy it first. & exit /b 1 )
echo   bucket: %BUCKET%
echo   api:    %API%

echo Building the app...
pushd "%FRONTEND%"
if not exist node_modules (
  call npm ci || ( popd & exit /b 1 )
)
call npm run build || ( popd & exit /b 1 )
popd

rem Runtime config: the same build works for any account.
> "%OUT%\config.json" echo {"apiUrl":"%API%"}

echo Uploading...
rem Hashed assets first (long cache), then index.html and config.json (always revalidated).
aws s3 sync "%OUT%" s3://%BUCKET% --delete --exclude index.html --exclude config.json --cache-control "public,max-age=31536000,immutable" %OPTS% || exit /b 1
aws s3 cp "%OUT%\config.json" s3://%BUCKET%/config.json --cache-control "no-cache" --content-type "application/json" %OPTS% || exit /b 1
aws s3 cp "%OUT%\index.html" s3://%BUCKET%/index.html --cache-control "no-cache" --content-type "text/html; charset=utf-8" %OPTS% || exit /b 1

echo Invalidating CloudFront cache...
aws cloudfront create-invalidation --distribution-id %DIST% --paths "/index.html" "/config.json" --query "Invalidation.Id" --output text %OPTS% || exit /b 1

echo.
echo Done: %SITE%
echo Debug panel: %SITE%/?debug
exit /b 0
