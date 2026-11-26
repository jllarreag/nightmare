@echo off
setlocal EnableDelayedExpansion
rem Create, list and close AWS Organizations member accounts using plain aws CLI calls.
rem Run with a profile of the management account and an active SSO session:
rem   aws sso login --profile ^<profile^>
rem
rem Usage:
rem   org-accounts.bat PROFILE list
rem   org-accounts.bat PROFILE ous
rem   org-accounts.bat PROFILE create ACCOUNT_NAME EMAIL [OU_ID]
rem   org-accounts.bat PROFILE remove ACCOUNT_ID

set "PROFILE=%~1"
set "ACTION=%~2"
if "%PROFILE%"=="" goto usage
if "%ACTION%"=="" goto usage

rem Organizations is a global service served from us-east-1.
set "ORG=aws organizations"
set "OPTS=--profile %PROFILE% --region us-east-1"

if /i "%ACTION%"=="list"   goto do_list
if /i "%ACTION%"=="ous"    goto do_ous
if /i "%ACTION%"=="create" goto do_create
if /i "%ACTION%"=="remove" goto do_remove
goto usage

:do_list
%ORG% list-accounts --query "Accounts[].[Id,Name,Email,Status]" --output table %OPTS%
exit /b %errorlevel%

:do_ous
for /f "delims=" %%R in ('%ORG% list-roots --query "Roots[0].Id" --output text %OPTS%') do set "ROOT=%%R"
if not defined ROOT ( echo Could not read the organization root. & exit /b 1 )
echo Root: %ROOT%
%ORG% list-organizational-units-for-parent --parent-id %ROOT% --query "OrganizationalUnits[].[Id,Name]" --output table %OPTS%
exit /b %errorlevel%

:do_create
set "NAME=%~3"
set "EMAIL=%~4"
set "OU_ID=%~5"
if "%NAME%"=="" goto usage
if "%EMAIL%"=="" goto usage

for /f "delims=" %%R in ('%ORG% create-account --account-name "%NAME%" --email "%EMAIL%" --role-name OrganizationAccountAccessRole --query "CreateAccountStatus.Id" --output text %OPTS%') do set "REQ=%%R"
if not defined REQ ( echo create-account failed. & exit /b 1 )
echo Request: %REQ%

:wait_loop
for /f "delims=" %%S in ('%ORG% describe-create-account-status --create-account-request-id %REQ% --query "CreateAccountStatus.State" --output text %OPTS%') do set "STATE=%%S"
echo   state: %STATE%
if /i "%STATE%"=="IN_PROGRESS" (
  timeout /t 5 /nobreak >nul
  goto wait_loop
)
if /i not "%STATE%"=="SUCCEEDED" (
  %ORG% describe-create-account-status --create-account-request-id %REQ% --query "CreateAccountStatus.FailureReason" --output text %OPTS%
  exit /b 1
)

for /f "delims=" %%A in ('%ORG% describe-create-account-status --create-account-request-id %REQ% --query "CreateAccountStatus.AccountId" --output text %OPTS%') do set "ACCOUNT_ID=%%A"

if not "%OU_ID%"=="" (
  for /f "delims=" %%P in ('%ORG% list-parents --child-id !ACCOUNT_ID! --query "Parents[0].Id" --output text %OPTS%') do set "SRC=%%P"
  %ORG% move-account --account-id !ACCOUNT_ID! --source-parent-id !SRC! --destination-parent-id %OU_ID% %OPTS%
  if errorlevel 1 exit /b 1
  echo Moved to %OU_ID%
)
echo Created account !ACCOUNT_ID!
exit /b 0

:do_remove
set "ACCOUNT_ID=%~3"
if "%ACCOUNT_ID%"=="" goto usage
%ORG% describe-account --account-id %ACCOUNT_ID% --query "Account.[Id,Name,Email]" --output text %OPTS%
if errorlevel 1 exit /b 1
set /p "CONFIRM=Type the account id to confirm closing: "
if not "%CONFIRM%"=="%ACCOUNT_ID%" ( echo Aborted. & exit /b 1 )
%ORG% close-account --account-id %ACCOUNT_ID% %OPTS%
if errorlevel 1 exit /b 1
echo Close requested (suspended for 90 days, then deleted).
exit /b 0

:usage
echo Usage:
echo   org-accounts.bat PROFILE list
echo   org-accounts.bat PROFILE ous
echo   org-accounts.bat PROFILE create ACCOUNT_NAME EMAIL [OU_ID]
echo   org-accounts.bat PROFILE remove ACCOUNT_ID
exit /b 1
